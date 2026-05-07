# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from collections import defaultdict, deque
from typing import Dict, List, Optional, Set, Tuple
import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


# =========================
# 1. 数据加载与缓存 (适配多页面架构)
# =========================
@st.cache_data(show_spinner="正在加载事故特征与图谱数据...")
def load_kg_data(excel_path: str, kg_path: str):
    """
    缓存数据读取过程，避免页面切换时反复触发磁盘I/O
    """
    df = pd.read_excel(excel_path)
    df.columns = [c.replace("道路线性", "道路线型") if isinstance(c, str) else c for c in df.columns]
    
    with open(kg_path, "r", encoding="utf-8") as f:
        graph = json.load(f)
        
    return df, graph


# =========================
# 2. KG utils
# =========================

def build_adj(graph: dict):
    adj = defaultdict(list)
    radj = defaultdict(list)
    for lk in graph["links"]:
        s = lk["source"]
        t = lk["target"]
        r = lk.get("reason", lk.get("relation", ""))
        adj[s].append((t, r))
        radj[t].append((s, r))
    return adj, radj

def bfs_collect(
    starts: List[str],
    adjacency: dict,
    max_hops: int,
    direction: str = "down",
) -> Set[Tuple[str, str, str]]:
    collected: Set[Tuple[str, str, str]] = set()
    visited_depth: Dict[str, int] = {}
    q = deque()

    for s in starts:
        q.append((s, 0))
        visited_depth[s] = 0

    while q:
        u, d = q.popleft()
        if d >= max_hops:
            continue

        for v, r in adjacency.get(u, []):
            if direction == "down":
                tri = (u, r, v)
                nxt = v
            else:
                tri = (v, r, u)
                nxt = v

            collected.add(tri)
            nd = d + 1
            if (nxt not in visited_depth) or (nd < visited_depth[nxt]):
                visited_depth[nxt] = nd
                q.append((nxt, nd))

    return collected

def select_links(
    relevant_links: Set[Tuple[str, str, str]],
    content_ids: Set[str],
    node_to_layer: Dict[str, str],
) -> List[Tuple[str, str, str]]:
    content_layers = {node_to_layer.get(nid, "") for nid in content_ids}
    filtered = []
    for s, r, t in relevant_links:
        ls = node_to_layer.get(s, "")
        lt = node_to_layer.get(t, "")
        if (ls in content_layers and s not in content_ids) or (lt in content_layers and t not in content_ids):
            continue
        filtered.append((s, r, t))
    return filtered

def find_and_merge(links: List[Tuple[str, str, str]]) -> List[List[Tuple[str, str, str]]]:
    remaining = list(links)
    chains: List[List[Tuple[str, str, str]]] = []

    while remaining:
        current_chain = [remaining.pop(0)]
        chain_nodes = {current_chain[0][0], current_chain[0][2]}

        extended = True
        while extended:
            extended = False
            for lk in list(remaining):
                h, r, t = lk

                if current_chain[-1][2] == h and t not in chain_nodes:
                    current_chain.append(lk)
                    remaining.remove(lk)
                    chain_nodes.add(t)
                    extended = True
                    break

                if current_chain[0][0] == t and h not in chain_nodes:
                    current_chain.insert(0, lk)
                    remaining.remove(lk)
                    chain_nodes.add(h)
                    extended = True
                    break

        chains.append(current_chain)

    return chains

def score_chains(
    chains: List[List[Tuple[str, str, str]]],
    important_nodes: Set[str],
    weight: float = 0.7,
    distance: float = 1.5,
):
    scored = []
    for chain in chains:
        unique_nodes = set()
        for h, r, t in chain:
            unique_nodes.add(h)
            unique_nodes.add(t)

        if important_nodes:
            important_node_count = len(unique_nodes & important_nodes)
            coverage_ratio = important_node_count / len(important_nodes)
        else:
            important_node_count = 0
            coverage_ratio = 0.0

        expansion_ratio = important_node_count / len(unique_nodes) if unique_nodes else 0.0
        score = (1 - weight) * (distance - expansion_ratio) + weight * coverage_ratio

        scored.append(
            dict(
                chain=chain,
                score=score,
                coverage_ratio=coverage_ratio,
                expansion_ratio=expansion_ratio,
                important_node_count=important_node_count,
                unique_nodes=unique_nodes,
            )
        )

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


# =========================
# 3. Code -> Chinese KG entity names
# =========================
WEATHER_CODE_MAP = {1: "晴朗", 2: "阴雨", 3: "冰雪", 4: "沙尘"}
LIGHT_CODE_MAP = {1: "白天", 2: "夜间"}
SCENE_CODE_MAP = {1: "高速公路", 2: "快速路", 3: "公路", 4: "城市路段", 5: "其他道路"}
LINEAR_CODE_MAP = {1: "直线段", 2: "曲线段", 3: "城市交叉口", 4: "其他线形", 5: "上/下匝道"}

COL_WEATHER = ["weather(sunny,rainy,snowy,foggy)1-4", "weather"]
COL_LIGHT = ["light(day,night)1-2", "light"]
COL_SCENE = ["scenes(highway,tunnel,mountain,urban,rural)1-5", "scenes", "scene"]
COL_LINEAR = ["linear(arterials,curve,intersection,T-junction,ramp) 1-5", "linear", "道路线型", "道路线性"]

def norm_cell(x) -> Optional[str]:
    if pd.isna(x):
        return None
    s = str(x).strip()
    if not s or s.lower() == "nan":
        return None
    return s

def align_entity(name: Optional[str], node_ids: Set[str]) -> Optional[str]:
    if name is None:
        return None
    name = str(name).strip()
    return name if name in node_ids else None

def get_code(row: pd.Series, col_candidates: List[str]) -> Optional[int]:
    for col in col_candidates:
        if col in row and not pd.isna(row[col]):
            try:
                return int(row[col])
            except Exception:
                try:
                    return int(float(row[col]))
                except Exception:
                    return None
    return None

def row_to_inputs(row: pd.Series, node_ids: Set[str]) -> Tuple[List[str], List[str]]:
    inputs: List[str] = []
    notes: List[str] = []

    acc = norm_cell(row.get("事故类型"))
    acc_aligned = align_entity(acc, node_ids)
    if acc_aligned:
        inputs.append(acc_aligned)
    elif acc:
        notes.append(f"事故类型未对齐: {acc}")

    w = get_code(row, COL_WEATHER)
    l = get_code(row, COL_LIGHT)
    s = get_code(row, COL_SCENE)
    lin = get_code(row, COL_LINEAR)

    for _, code, mp in [
        ("weather", w, WEATHER_CODE_MAP),
        ("light", l, LIGHT_CODE_MAP),
        ("scenes", s, SCENE_CODE_MAP),
        ("linear", lin, LINEAR_CODE_MAP),
    ]:
        if code is None:
            continue
        ent = mp.get(code)
        ent_aligned = align_entity(ent, node_ids)
        if ent_aligned:
            inputs.append(ent_aligned)

    inputs = list(dict.fromkeys(inputs))
    return inputs, notes

def run_retrieval(input_entities: List[str], adj: dict, radj: dict, node_to_layer: Dict[str, str]):
    downstream = bfs_collect(input_entities, adj, max_hops=4, direction="down")
    upstream = bfs_collect(input_entities, radj, max_hops=2, direction="up")
    relevant_links = downstream | upstream

    filtered_links = select_links(relevant_links, set(input_entities), node_to_layer)
    chains = find_and_merge(filtered_links)
    scored = score_chains(chains, important_nodes=set(input_entities), weight=0.7, distance=1.5)
    return scored, filtered_links


# =========================
# 4. 可视化相关辅助函数
# =========================

def safe_get_layer_name(layer_raw, idx: int) -> str:
    if layer_raw is None:
        return f"层级{idx}"
    s = str(layer_raw).strip()
    return s if s else f"层级{idx}"

def pairwise_layers(layer_names: List[str]) -> List[List[str]]:
    rows = []
    i = 0
    while i < len(layer_names):
        if i + 1 < len(layer_names):
            rows.append([layer_names[i], layer_names[i + 1]])
        else:
            rows.append([layer_names[i]])
        i += 2
    return rows

def dedupe_links_preserve_order(links: List[Tuple[str, str, str]]) -> List[Tuple[str, str, str]]:
    seen = set()
    out = []
    for lk in links:
        if lk not in seen:
            seen.add(lk)
            out.append(lk)
    return out

def prepare_graph_meta(graph: dict):
    node_ids = set()
    node_to_layer: Dict[str, str] = {}
    layer_to_nodes = defaultdict(list)
    layer_order: List[str] = []

    for idx, n in enumerate(graph["nodes"]):
        nid = n["id"]
        node_ids.add(nid)
        layer = safe_get_layer_name(n.get("layer", "未分类"), idx)
        node_to_layer[nid] = layer
        layer_to_nodes[layer].append(nid)
        if layer not in layer_order:
            layer_order.append(layer)

    for layer in layer_to_nodes:
        layer_to_nodes[layer] = sorted(set(layer_to_nodes[layer]))

    return node_ids, node_to_layer, layer_to_nodes, layer_order

def extract_subgraph(scored, selected_inputs: List[str], top_k: int = 3):
    sub_links: List[Tuple[str, str, str]] = []
    sub_nodes: Set[str] = set(selected_inputs)

    for item in scored[:top_k]:
        for s, r, t in item["chain"]:
            sub_links.append((s, r, t))
            sub_nodes.add(s)
            sub_nodes.add(t)

    sub_links = dedupe_links_preserve_order(sub_links)
    return sorted(sub_nodes), sub_links

def build_layered_positions(
    node_names: List[str],
    node_to_layer: Dict[str, str],
    layer_order: List[str],
) -> Dict[str, Tuple[float, float]]:
    layer_to_subset_nodes = defaultdict(list)
    for node in node_names:
        layer_to_subset_nodes[node_to_layer.get(node, "未分类")].append(node)

    positions: Dict[str, Tuple[float, float]] = {}
    used_layers = [layer for layer in layer_order if layer in layer_to_subset_nodes]
    if not used_layers:
        used_layers = sorted(layer_to_subset_nodes.keys())

    x_gap = 2.8
    for lx, layer in enumerate(used_layers):
        nodes = sorted(layer_to_subset_nodes[layer])
        n = len(nodes)
        if n == 1:
            y_values = [0.0]
        else:
            y_values = [((n - 1) / 2.0) - i for i in range(n)]
        for node, y in zip(nodes, y_values):
            positions[node] = (lx * x_gap, y * 1.45)

    for node in node_names:
        if node not in positions:
            positions[node] = (0.0, 0.0)
    return positions

def get_layer_color_map(layer_order: List[str]) -> Dict[str, str]:
    palette = [
        "#4C78A8", "#F58518", "#54A24B", "#E45756", "#72B7B2", "#B279A2",
        "#FF9DA6", "#9D755D", "#BAB0AC", "#5F6B6D", "#8E6C8A", "#2F4B7C",
        "#A05195", "#D45087", "#F95D6A", "#FF7C43", "#FFA600",
    ]
    return {layer: palette[i % len(palette)] for i, layer in enumerate(layer_order)}

def build_plotly_graph(
    node_names: List[str],
    links: List[Tuple[str, str, str]],
    node_to_layer: Dict[str, str],
    layer_order: List[str],
    title: str,
    highlighted_nodes: Optional[Set[str]] = None,
    show_edge_labels: bool = False,
    height: int = 500,
):
    highlighted_nodes = highlighted_nodes or set()
    positions = build_layered_positions(node_names, node_to_layer, layer_order)
    layer_color_map = get_layer_color_map(layer_order)

    edge_color_map = {
        "导致": "#FF6B6B",
        "加剧": "#F59E0B",
        "减轻": "#10B981",
        "可能": "#60A5FA",
        "影响": "#A78BFA",
        "促使": "#F472B6",
        "伴随": "#94A3B8",
        "": "#6B7280",
    }

    fig = go.Figure()

    for s, r, t in links:
        if s not in positions or t not in positions:
            continue
        x0, y0 = positions[s]
        x1, y1 = positions[t]
        fig.add_trace(
            go.Scatter(
                x=[x0, x1, None],
                y=[y0, y1, None],
                mode="lines",
                line=dict(color=edge_color_map.get(r, "#6B7280"), width=1.8),
                hoverinfo="text",
                text=[f"{s} → {t}<br>关系：{r}", f"{s} → {t}<br>关系：{r}", None],
                showlegend=False,
            )
        )
        if show_edge_labels:
            mx = (x0 + x1) / 2.0
            my = (y0 + y1) / 2.0
            fig.add_trace(
                go.Scatter(
                    x=[mx],
                    y=[my],
                    mode="text",
                    text=[r],
                    textfont=dict(size=11, color="#111111"),
                    hoverinfo="skip",
                    showlegend=False,
                )
            )

    nodes_by_layer = defaultdict(list)
    for node in node_names:
        layer = node_to_layer.get(node, "未分类")
        nodes_by_layer[layer].append(node)

    ordered_layers = [layer for layer in layer_order if layer in nodes_by_layer]
    for layer in ordered_layers:
        nodes = sorted(nodes_by_layer[layer])
        xs = [positions[n][0] for n in nodes]
        ys = [positions[n][1] for n in nodes]
        sizes = [24 if n in highlighted_nodes else 17 for n in nodes]
        line_widths = [2.6 if n in highlighted_nodes else 1.0 for n in nodes]
        hover_text = [f"节点：{n}<br>层级：{layer}" for n in nodes]

        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="markers+text",
                text=nodes,
                textposition="top center",
                textfont=dict(size=11, color="#111111"),
                hovertext=hover_text,
                hoverinfo="text",
                marker=dict(
                    size=sizes,
                    color=layer_color_map.get(layer, "#4B5563"),
                    line=dict(color="#FFFFFF", width=line_widths),
                    opacity=0.96,
                ),
                name=layer,
                showlegend=False,
            )
        )

    fig.update_layout(
        title=title,
        height=height,
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(color="#111111"),
        showlegend=False,
        margin=dict(l=20, r=20, t=60, b=20),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        hovermode="closest",
    )
    return fig


# =========================
# 5. 渲染入口函数 (暴露给主应用调用)
# =========================
def show_cause_page():
    # ---------------- 硬编码文件路径配置 ----------------
    # 请确保这两个文件存放在系统运行的同级目录下，或修改为绝对路径
    EXCEL_PATH = "data/cause_raw_data.xlsx" 
    KG_PATH = "data/cause_kg.json"
    
    if not os.path.exists(EXCEL_PATH) or not os.path.exists(KG_PATH):
        st.error(f"无法找到数据文件，请检查路径：\nExcel: {EXCEL_PATH}\nJSON: {KG_PATH}")
        return

    # 加载缓存的数据
    df, graph = load_kg_data(EXCEL_PATH, KG_PATH)

    node_ids, node_to_layer, layer_to_nodes, layer_order = prepare_graph_meta(graph)
    adj, radj = build_adj(graph)

    # 注入局部 CSS 样式 (注释掉了会污染全站的背景配置)
    st.markdown(
        """
        <style>
        
        .main-title {
            color: #374151; /* 深灰，和目标界面标题色一致 */
            font-size: 2.2rem;
            font-weight: 700;
            line-height: 1.35;
            margin-top: 0.1rem;
            margin-bottom: 0.9rem;
            white-space: normal;
            word-break: break-word;
            overflow: visible;
        }
        .small-hint {
            color: #6b7280; /* 浅灰提示文字 */
            font-size: 0.92rem;
            margin-top: -0.2rem;
            margin-bottom: 0.8rem;
        }
        .section-box {
            border: 1px solid #e5e7eb; /* 浅灰色边框 */
            border-radius: 16px;
            padding: 0.8rem 0.9rem 0.4rem 0.9rem;
            background: #ffffff; /* 白色背景 */
            margin-bottom: 0.8rem;
            color: #111111; /* 深色文字 */
        }
        .layer-label {
            font-size: 14px;
            font-weight: 600;
            color: #374151; /* 深灰标签 */
            margin-top: 4px;
            margin-bottom: 4px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="main-title">事故致因自动化匹配</div>', unsafe_allow_html=True)

    vids = df["video"].tolist() if "video" in df.columns else list(range(len(df)))
    
    # Session State 命名空间隔离，防止和其他页面的选框冲突
    selected_vid = st.session_state.get("cause_selected_vid", vids[0])
    if selected_vid not in vids:
        selected_vid = vids[0]

    left_col, right_col = st.columns([0.95, 1.45], gap="large")

    with left_col:
        st.markdown('<div class="section-box">', unsafe_allow_html=True)
        st.subheader("事故特征选择")
        selected_vid = st.selectbox(
            "MM-AU数据编号",
            vids,
            index=vids.index(selected_vid),
            key="cause_selected_vid",  # 键名隔离
        )

        row = df[df["video"] == selected_vid].iloc[0] if "video" in df.columns else df.iloc[int(selected_vid)]
        default_inputs, notes = row_to_inputs(row, node_ids)

        selected_inputs: List[str] = []
        layer_names = sorted(layer_to_nodes.keys())
        default_by_layer = {}
        for ent in default_inputs:
            lay = node_to_layer.get(ent)
            if lay and lay not in default_by_layer:
                default_by_layer[lay] = ent

        layer_rows = pairwise_layers(layer_names)
        for row_layers in layer_rows:
            cols = st.columns(2, gap="medium")
            for j in range(2):
                with cols[j]:
                    if j < len(row_layers):
                        layer = row_layers[j]
                        options = [""] + layer_to_nodes[layer]
                        default_value = default_by_layer.get(layer, "")
                        default_index = options.index(default_value) if default_value in options else 0

                        st.markdown(f'<div class="layer-label">{layer}</div>', unsafe_allow_html=True)
                        chosen = st.selectbox(
                            label=layer,
                            options=options,
                            index=default_index,
                            key=f"cause_layer_select_{selected_vid}_{layer}", # 键名隔离
                            label_visibility="collapsed",
                        )
                        if chosen != "":
                            selected_inputs.append(chosen)

        selected_inputs = list(dict.fromkeys(selected_inputs))
        st.markdown('</div>', unsafe_allow_html=True)

        if notes:
            for note in notes:
                st.warning(note)

    scored, filtered_links = run_retrieval(selected_inputs, adj, radj, node_to_layer) if selected_inputs else ([], [])
    sub_nodes, sub_links = extract_subgraph(scored, selected_inputs, top_k=3) if selected_inputs else ([], [])

    full_node_names = [n["id"] for n in graph["nodes"]]
    full_links = [
        (lk["source"], lk.get("reason", lk.get("relation", "")), lk["target"])
        for lk in graph["links"]
    ]

    with right_col:
        with st.expander("检索得到的子图", expanded=False):
            if not selected_inputs:
                st.info("请先在左侧选择事故特征。")
            elif not sub_links:
                st.warning("当前选择下未检索到可展示的子图链路。")
            else:
                st.caption(
                    f"当前输入特征：{', '.join(selected_inputs)} ｜ 子图节点数：{len(sub_nodes)} ｜ 子图边数：{len(sub_links)}"
                )
                sub_fig = build_plotly_graph(
                    node_names=sub_nodes,
                    links=sub_links,
                    node_to_layer=node_to_layer,
                    layer_order=layer_order,
                    title="检索得到的子图（Top-3 链路并集）",
                    highlighted_nodes=set(selected_inputs),
                    show_edge_labels=True,
                    height=460,
                )
                st.plotly_chart(sub_fig, use_container_width=True)

                chain_titles = []
                for idx, item in enumerate(scored[:3], start=1):
                    chain_text = "  |  ".join([f"{s} —[{r}]→ {t}" for s, r, t in item["chain"]])
                    chain_titles.append(f"链路 {idx}: {chain_text}")
                if chain_titles:
                    st.markdown("<br>".join(chain_titles), unsafe_allow_html=True)

        st.subheader("完整可视化知识图谱")
        full_fig = build_plotly_graph(
            node_names=full_node_names,
            links=full_links,
            node_to_layer=node_to_layer,
            layer_order=layer_order,
            title="完整知识图谱",
            highlighted_nodes=set(selected_inputs),
            show_edge_labels=False,
            height=880,
        )
        st.plotly_chart(full_fig, use_container_width=True)

        if filtered_links:
            st.caption(f"当前检索实际命中的候选边数：{len(filtered_links)}。完整图中高亮节点为当前左侧已选事故特征。")

# 如果允许独立运行测试，保留此代码块（可选）
if __name__ == "__main__":
    st.set_page_config(page_title="独立测试-致因匹配系统", layout="wide")
    show_cause_page()
