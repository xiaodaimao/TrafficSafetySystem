import json
import pandas as pd
from collections import defaultdict, deque
import os

class CauseRetrievalEngine:
    def __init__(self, data_dir):
        """初始化引擎，加载数据集和致因知识图谱"""
        excel_path = os.path.join(data_dir, "cause_raw_data.xlsx")
        kg_path = os.path.join(data_dir, "cause_kg.json")

        # 1. 加载 Excel 数据
        self.df = pd.read_excel(excel_path)
        self.df.columns = [c.replace("道路线性", "道路线型") if isinstance(c, str) else c for c in self.df.columns]
        self.vids = self.df["video"].tolist() if "video" in self.df.columns else list(range(len(self.df)))

        # 2. 加载 JSON 图谱
        with open(kg_path, "r", encoding="utf-8") as f:
            self.graph = json.load(f)

        self.node_ids = set(n["id"] for n in self.graph["nodes"])
        self.node_to_layer = {}
        self.layer_to_nodes = defaultdict(list)

        for idx, n in enumerate(self.graph["nodes"]):
            nid = n["id"]
            layer = self._safe_get_layer_name(n.get("layer", "未分类"), idx)
            self.node_to_layer[nid] = layer
            self.layer_to_nodes[layer].append(nid)

        for layer in self.layer_to_nodes:
            self.layer_to_nodes[layer] = sorted(set(self.layer_to_nodes[layer]))

        self.adj, self.radj = self._build_adj(self.graph)

        # 3. 映射字典常量
        self.WEATHER_CODE_MAP = {1: "晴朗", 2: "阴雨", 3: "冰雪", 4: "沙尘"}
        self.LIGHT_CODE_MAP = {1: "白天", 2: "夜间"}
        self.SCENE_CODE_MAP = {1: "高速公路", 2: "快速路", 3: "公路", 4: "城市路段", 5: "其他道路"}
        self.LINEAR_CODE_MAP = {1: "直线段", 2: "曲线段", 3: "城市交叉口", 4: "其他线形", 5: "上/下匝道"}
        self.COL_WEATHER = ["weather(sunny,rainy,snowy,foggy)1-4", "weather"]
        self.COL_LIGHT = ["light(day,night)1-2", "light"]
        self.COL_SCENE = ["scenes(highway,tunnel,mountain,urban,rural)1-5", "scenes", "scene"]
        self.COL_LINEAR = ["linear(arterials,curve,intersection,T-junction,ramp) 1-5", "linear", "道路线型", "道路线性"]

    # =========================
    # 数据提取相关功能
    # =========================
    def get_video_ids(self):
        return self.vids

    def get_row_data(self, vid):
        return self.df[self.df["video"] == vid].iloc[0] if "video" in self.df.columns else self.df.iloc[int(vid)]

    def get_inputs_and_keys(self, vid):
        row = self.get_row_data(vid)
        inputs, _ = self._row_to_inputs(row)
        key_elems = self._row_to_key_elements(row)
        return inputs, key_elems

    # =========================
    # 核心检索算法 (复用原代码)
    # =========================
    def run_retrieval(self, input_entities):
        if not input_entities:
            return [], set(), 0.0

        downstream = self._bfs_collect(input_entities, self.adj, max_hops=4, direction="down")
        upstream = self._bfs_collect(input_entities, self.radj, max_hops=2, direction="up")
        relevant_links = downstream | upstream

        filtered_links = self._select_links(relevant_links, set(input_entities))
        chains = self._find_and_merge(filtered_links)
        scored = self._score_chains(chains, important_nodes=set(input_entities), weight=0.7, distance=1.5)
        
        top3 = scored[:3]
        union_nodes = set()
        for it in top3:
            union_nodes |= it["unique_nodes"]
            
        return top3, union_nodes

    # 以下均为底层私有辅助函数（从师兄代码完整迁移，只加了 self）
    def _safe_get_layer_name(self, layer_raw, idx):
        if layer_raw is None: return f"层级{idx}"
        s = str(layer_raw).strip()
        return s if s else f"层级{idx}"

    def _build_adj(self, graph):
        adj = defaultdict(list)
        radj = defaultdict(list)
        for lk in graph["links"]:
            s, t, r = lk["source"], lk["target"], lk.get("reason", lk.get("relation", ""))
            adj[s].append((t, r))
            radj[t].append((s, r))
        return adj, radj

    def _bfs_collect(self, starts, adjacency, max_hops, direction="down"):
        collected, visited_depth, q = set(), {}, deque()
        for s in starts:
            q.append((s, 0))
            visited_depth[s] = 0
        while q:
            u, d = q.popleft()
            if d >= max_hops: continue
            for v, r in adjacency.get(u, []):
                tri, nxt = ((u, r, v), v) if direction == "down" else ((v, r, u), v)
                collected.add(tri)
                nd = d + 1
                if (nxt not in visited_depth) or (nd < visited_depth[nxt]):
                    visited_depth[nxt] = nd
                    q.append((nxt, nd))
        return collected

    def _select_links(self, relevant_links, content_ids):
        content_layers = {self.node_to_layer.get(nid, "") for nid in content_ids}
        filtered = []
        for s, r, t in relevant_links:
            ls, lt = self.node_to_layer.get(s, ""), self.node_to_layer.get(t, "")
            if (ls in content_layers and s not in content_ids) or (lt in content_layers and t not in content_ids): continue
            filtered.append((s, r, t))
        return filtered

    def _find_and_merge(self, links):
        remaining, chains = list(links), []
        while remaining:
            current_chain = [remaining.pop(0)]
            chain_nodes = {current_chain[0][0], current_chain[0][2]}
            extended = True
            while extended:
                extended = False
                for lk in list(remaining):
                    h, r, t = lk
                    if current_chain[-1][2] == h and t not in chain_nodes:
                        current_chain.append(lk); remaining.remove(lk); chain_nodes.add(t); extended = True; break
                    if current_chain[0][0] == t and h not in chain_nodes:
                        current_chain.insert(0, lk); remaining.remove(lk); chain_nodes.add(h); extended = True; break
            chains.append(current_chain)
        return chains

    def _score_chains(self, chains, important_nodes, weight, distance):
        scored = []
        for chain in chains:
            unique_nodes = set()
            for h, r, t in chain: unique_nodes.update([h, t])
            imp_count = len(unique_nodes & important_nodes) if important_nodes else 0
            cov_ratio = imp_count / len(important_nodes) if important_nodes else 0.0
            exp_ratio = imp_count / len(unique_nodes) if unique_nodes else 0.0
            score = (1 - weight) * (distance - exp_ratio) + weight * cov_ratio
            scored.append(dict(chain=chain, score=score, unique_nodes=unique_nodes))
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored

    def _row_to_inputs(self, row):
        inputs, notes = [], []
        acc = self._norm_cell(row.get("事故类型"))
        if acc_aligned := self._align_entity(acc): inputs.append(acc_aligned)
        
        w = self._get_code(row, self.COL_WEATHER)
        l = self._get_code(row, self.COL_LIGHT)
        s = self._get_code(row, self.COL_SCENE)
        lin = self._get_code(row, self.COL_LINEAR)

        for _, code, mp in [("w", w, self.WEATHER_CODE_MAP), ("l", l, self.LIGHT_CODE_MAP), ("s", s, self.SCENE_CODE_MAP), ("lin", lin, self.LINEAR_CODE_MAP)]:
            if code is not None:
                if ent_aligned := self._align_entity(mp.get(code)): inputs.append(ent_aligned)
        return list(dict.fromkeys(inputs)), notes

    def _row_to_key_elements(self, row):
        elems = []
        for c in ["要素1", "要素2", "要素3"]:
            if v := self._norm_cell(row.get(c)):
                if v_aligned := self._align_entity(v): elems.append(v_aligned)
        return list(dict.fromkeys(elems))

    def _norm_cell(self, x):
        if pd.isna(x): return None
        s = str(x).strip()
        return None if not s or s.lower() == "nan" else s

    def _align_entity(self, name):
        if name is None: return None
        name = str(name).strip()
        return name if name in self.node_ids else None
    
    def _get_code(self, row, col_candidates):
        for col in col_candidates:
            if col in row and not pd.isna(row[col]):
                try: return int(float(row[col]))
                except: return None
        return None