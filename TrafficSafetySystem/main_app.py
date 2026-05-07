import streamlit as st
import streamlit.components.v1 as components
import os

# 导入我们写好的两个子页面模块
# 注意：之前我们在子页面里写的 st.set_page_config 是在 if __name__ == "__main__": 里的，
# 所以这里 import 不会报错。
from page_risk import show_risk_page
from page_cause import show_cause_page

# 1. 必须在第一行设置全局页面配置
st.set_page_config(
    page_title="交通场景风险推理与致因溯源",
    page_icon="🚦",
    layout="wide",
    initial_sidebar_state="collapsed" # 默认收起侧边栏，让主页面更宽阔
)

# 2. 初始化页面路由状态
if 'current_page' not in st.session_state:
    st.session_state.current_page = 'home'

# 页面跳转回调函数
def navigate_to(page_name):
    st.session_state.current_page = page_name

# ==========================================
# 页面 1：系统主页 (全局图谱与导航)
# ==========================================
if st.session_state.current_page == 'home':
    # 主标题
    st.markdown("<h2 style='text-align: center; color: #1f2d3d;'>🚦 交通场景风险推理与致因溯源系统</h2>", unsafe_allow_html=True)

    # 居中显示全量图谱 (调用你原本的 full_graph.html)
    graph_path = "./static/full_graph.html"
    if os.path.exists(graph_path):
        with open(graph_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        # 渲染 HTML，高度稍微调大，使其有震撼的全局观感
        components.html(html_content, height=600)
    else:
        st.warning(f"未找到全局知识图谱文件：`{graph_path}`。请确认文件路径是否正确。")


    # 注入 CSS：右下角常驻悬浮窗图例 & 底部按钮美化
    st.markdown("""
    <style>
    /* 悬浮图例样式 */
    .legend-box {
        position: fixed;
        bottom: 120px; /* 避开底部导航按钮 */
        right: 30px;
        background-color: rgba(255, 255, 255, 0.95);
        padding: 15px 20px;
        border-radius: 10px;
        border: 1px solid #dde6f0;
        box-shadow: 0 8px 24px rgba(31,45,61,0.1);
        z-index: 9999;
    }
    .legend-title {
        font-weight: 700;
        margin-bottom: 12px;
        color: #1f2d3d;
        font-size: 16px;
        text-align: center;
        border-bottom: 2px solid #edf2f7;
        padding-bottom: 5px;
    }
    .legend-item { 
        margin-bottom: 8px; 
        font-size: 14px; 
        color: #3c4858; 
        display: flex;
        align-items: center;
    }
    .dot { 
        height: 14px; 
        width: 14px; 
        border-radius: 50%; 
        display: inline-block; 
        margin-right: 10px; 
    }
    </style>
    
    <div class="legend-box">
        <div class="legend-title">📍 图例说明</div>
        <div class="legend-item"><span class="dot" style="background-color: #ff6b6b;"></span>场景节点</div>
        <div class="legend-item"><span class="dot" style="background-color: #999999;"></span>路段类型</div>
        <div class="legend-item"><span class="dot" style="background-color: #4ecdc4;"></span>道路线形</div>
        <div class="legend-item"><span class="dot" style="background-color: #96ceb4;"></span>前方车道数变化</div>
        <div class="legend-item"><span class="dot" style="background-color: #ffeead;"></span>路段长度</div>
        <div class="legend-item"><span class="dot" style="background-color: #d4a5a5;"></span>中央隔离带设置情况</div>
        <div class="legend-item"><span class="dot" style="background-color: #9b59b6;"></span>临时管制措施</div>
        <div class="legend-item"><span class="dot" style="background-color: #3498db;"></span>工作日情况</div>
        <div class="legend-item"><span class="dot" style="background-color: #e595b2;"></span>出行时段</div>
        <div class="legend-item"><span class="dot" style="background-color: #f1c40f;"></span>能见度</div>
        <div class="legend-item"><span class="dot" style="background-color: #2fcc71;"></span>路面情况</div>
        <div class="legend-item"><span class="dot" style="background-color: #1abc9d;"></span>天气</div>
        <div class="legend-item"><span class="dot" style="background-color: #FFA500;"></span>路侧照明</div>
    </div>
    """, unsafe_allow_html=True)

    # 底部导航引导区域
    st.markdown("<hr style='margin-top: 1rem; margin-bottom: 2rem;'>", unsafe_allow_html=True)
    
    # 使用空白列将按钮居中并列排布
    col1, col_btn1, col_space, col_btn2, col2 = st.columns([1, 3, 0.5, 3, 1])
    
    with col_btn1:
        st.button(
            "🔍 进入 【场景风险推理】", 
            on_click=navigate_to, 
            args=('risk',), 
            use_container_width=True, 
            type="primary"
        )

    with col_btn2:
        st.button(
            "🔗 进入 【致因链检索】", 
            on_click=navigate_to, 
            args=('cause',), 
            use_container_width=True, 
            type="primary"
        )

# ==========================================
# 页面 2：场景风险推理界面
# ==========================================
elif st.session_state.current_page == 'risk':
    # 顶部返回按钮
    st.button("⬅️ 返回主页", on_click=navigate_to, args=('home',))
    st.markdown("---")
    # 调用 page_risk.py 中的展示逻辑
    show_risk_page()


# ==========================================
# 页面 3：致因链检索界面
# ==========================================
elif st.session_state.current_page == 'cause':
    # 顶部返回按钮
    st.button("⬅️ 返回主页", on_click=navigate_to, args=('home',))
    st.markdown("---")
    # 调用 page_cause.py 中的展示逻辑
    show_cause_page()