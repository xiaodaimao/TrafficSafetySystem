import streamlit as st
from utils.cause_engine import CauseRetrievalEngine

def render_chip_html(items, empty_text="空"):
    if not items:
        return f'<div class="empty-text">{empty_text}</div>'
    return "".join([f'<span class="tag-item">{x}</span>' for x in items])

def begin_card(title):
    try:
        box = st.container(border=True)
    except TypeError:
        box = st.container()
    with box:
        st.markdown(f"#### {title}")
    return box

def show_cause_page():
    # 1. 缓存加载后台引擎，避免重复读取数据
    @st.cache_resource
    def load_engine():
        return CauseRetrievalEngine(data_dir="data")
    
    engine = load_engine()

    # 2. 注入统一风格的浅色 CSS 样式
    st.markdown("""
    <style>
    .stApp {
        background: linear-gradient(180deg, #f7f9fc 0%, #edf2f7 100%);
    }

    .block-container {
        max-width: 1320px;
        padding-top: 2rem;
        padding-bottom: 1.2rem;
    }

    .main-title-wrap {
        padding-top: 0.35rem;
        padding-bottom: 0.55rem;
        margin-bottom: 1rem;
    }

    .main-title {
        display: block;
        font-size: 31px;
        font-weight: 700;
        color: #1f2d3d;
        line-height: 1.35;
        letter-spacing: 0.2px;
        margin: 0;
    }

    /* 覆盖掉系统默认样式，强制文字变深色 */
    h1, h2, h3, h4, p, label, span {
        color: #1f2d3d !important;
    }

    .tag-wrap {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        align-items: flex-start;
        margin-bottom: 10px;
    }

    .tag-item {
        display: inline-block;
        padding: 7px 13px;
        border-radius: 999px;
        background: #edf3fb;
        border: 1px solid #d9e6f5;
        color: #243647 !important;
        font-size: 14px;
        font-weight: 500;
        line-height: 1.3;
    }

    .empty-text {
        font-size: 15px;
        color: #8b98a7 !important;
        margin-top: 4px;
    }

    .hint-title {
        font-size: 14px;
        color: #637385 !important;
        margin-bottom: 8px;
        font-weight: 600;
    }

    .info-label {
        font-size: 14px;
        color: #617283 !important;
        margin-bottom: 4px;
    }

    .info-value {
        font-size: 18px;
        font-weight: 700;
        color: #1f2d3d !important;
        line-height: 1.25;
    }

    .result-ok {
        color: #167c3c !important;
        font-size: 24px;
        font-weight: 800;
    }

    .result-bad {
        color: #b42318 !important;
        font-size: 24px;
        font-weight: 800;
    }

    .score-value {
        color: #1d4f91 !important;
        font-size: 22px;
        font-weight: 700;
    }

    .layer-label {
        font-size: 14px;
        font-weight: 600;
        color: #2a3a4a !important;
        margin-top: 6px;
        margin-bottom: 4px;
    }

    div[data-testid="stSelectbox"] > div,
    div[data-baseweb="select"] > div {
        font-size: 14px !important;
    }

    /* 将 Selectbox 恢复成白底黑字 */
    div[data-baseweb="select"] > div {
        background: #ffffff !important;
        border-color: #dde6f0 !important;
        color: #1f2d3d !important;
    }

    /* 容器卡片的浅色主题重写 */
    div[data-testid="stVerticalBlockBorderWrapper"] {
        background: rgba(255,255,255,0.96) !important;
        border: 1px solid #dde6f0 !important;
        border-radius: 14px !important;
        padding: 12px 14px !important;
        box-shadow: 0 4px 12px rgba(31,45,61,0.03) !important;
    }

    div[data-testid="stLatex"] {
        background: transparent !important;
    }

    .katex-display {
        color: #1f2d3d !important;
        margin-top: 0.2rem !important;
        margin-bottom: 0 !important;
    }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("<h2 style='text-align: center; color: #1f2d3d;'>事故致因自动化匹配</h2>", unsafe_allow_html=True)

    # 3. 获取基础数据
    vids = engine.get_video_ids()
    selected_vid = st.session_state.get("selected_vid", vids[0])

    left_col, right_col = st.columns([1.05, 1], gap="large")

    with right_col:
        st.subheader("标记致因")
        selected_vid = st.selectbox(
            "MM-AU数据编号",
            vids,
            index=vids.index(selected_vid),
            key="selected_vid",
            label_visibility="collapsed"
        )

    default_inputs, key_elems = engine.get_inputs_and_keys(selected_vid)

    with left_col:
        st.subheader("事故特征")
        
        selected_inputs = []
        layer_names = sorted(engine.layer_to_nodes.keys())

        default_by_layer = {}
        for ent in default_inputs:
            lay = engine.node_to_layer.get(ent)
            if lay and lay not in default_by_layer:
                default_by_layer[lay] = ent

        layer_rows = []
        i = 0
        while i < len(layer_names):
            if i + 1 < len(layer_names):
                layer_rows.append([layer_names[i], layer_names[i + 1]])
            else:
                layer_rows.append([layer_names[i]])
            i += 2

        for row_layers in layer_rows:
            cols = st.columns(2, gap="medium")
            for j in range(2):
                with cols[j]:
                    if j < len(row_layers):
                        layer = row_layers[j]
                        options = [""] + engine.layer_to_nodes[layer]
                        default_value = default_by_layer.get(layer, "")
                        default_index = options.index(default_value) if default_value in options else 0

                        st.markdown(f'<div class="layer-label">{layer}</div>', unsafe_allow_html=True)
                        chosen = st.selectbox(
                            label=layer,
                            options=options,
                            index=default_index,
                            key=f"layer_select_{selected_vid}_{layer}",
                            label_visibility="collapsed"
                        )
                        if chosen != "":
                            selected_inputs.append(chosen)

        selected_inputs = list(dict.fromkeys(selected_inputs))

        hint_card = begin_card("参考事故特征")
        with hint_card:
            st.markdown('<div class="hint-title">当前样本可参考的事故特征</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="tag-wrap">{render_chip_html(default_inputs)}</div>', unsafe_allow_html=True)

    # 4. 执行检索
    if not selected_inputs:
        matched_elems = []
        match_ratio = 0.0
    else:
        top3_chains, union_nodes = engine.run_retrieval(selected_inputs)
        matched_elems = [x for x in key_elems if x in union_nodes]
        if key_elems:
            match_ratio = len(set(matched_elems)) / len(set(key_elems))
        else:
            match_ratio = 0.0

    is_matched = (match_ratio == 1.0 and len(key_elems) > 0)

    # 5. 右侧结果渲染
    with right_col:
        mark_card = begin_card("标记致因")
        with mark_card:
            st.markdown('<div class="info-label">MM-AU数据编号</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="info-value">{selected_vid}</div>', unsafe_allow_html=True)
            st.write("")
            st.markdown('<div class="info-label">真实的致因结果</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="tag-wrap">{render_chip_html(key_elems)}</div>', unsafe_allow_html=True)

        result_card = begin_card("致因自动化匹配结果")
        with result_card:
            st.markdown(f'<div class="tag-wrap">{render_chip_html(matched_elems)}</div>', unsafe_allow_html=True)

        score_card = begin_card("致因匹配度")
        with score_card:
            result_cls = "result-ok" if is_matched else "result-bad"
            result_text = "匹配" if is_matched else "不匹配"

            st.markdown('<div class="info-label">结果</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="{result_cls}">{result_text}</div>', unsafe_allow_html=True)
            st.write("")
            st.markdown('<div class="info-label">匹配度</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="score-value">r<sub>i</sub> = {match_ratio:.3f}</div>', unsafe_allow_html=True)
            st.write("")
            st.latex(r"r_i=\frac{|S_i\cap G_i|}{|G_i|}")

if __name__ == "__main__":
    show_cause_page()