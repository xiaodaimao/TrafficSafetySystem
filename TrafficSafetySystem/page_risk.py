import streamlit as st
import pandas as pd
import random
from pyvis.network import Network
import networkx as nx
import streamlit.components.v1 as components
import os

# 导入我们之前写好的推理引擎
from utils.inference import RiskInferenceEngine

# ==========================================
# 颜色配置 
# ==========================================
CATEGORY_COLORS = {
    "路段类型": "#999999", "线形": "#4ECDC4", "单向车道数": "#45B7D1",
    "前方车道数变化": "#96CEB4", "路段长度": "#FFEEAD", "中央隔离带设置情况": "#D4A5A5",
    "临时管制措施": "#9B59B6", "工作日情况": "#3498DB", "出行时段": "#e595b2",
    "能见度": "#F1C40F", "路面情况": "#2ECC71", "天气": "#1ABC9C",
    "时间": "#E67E22", "路侧照明": "#FFA500", "场景": "#662b31",
    "风险等级": "#ff0000", "事故类型": "#c51436"
}

def get_color(category):
    return CATEGORY_COLORS.get(category, '#999999')

# ==========================================
# 图谱交互的自定义 JavaScript (注入到 Pyvis 中)
# ==========================================
CUSTOM_JS = """
<script type="text/javascript">
    // 等待 network 对象初始化完成
    setTimeout(function() {
        if (typeof network !== 'undefined') {
            var allNodes = nodes.get();
            var allEdges = edges.get();
            
            // 存储图的初始状态
            var originalNodes = JSON.parse(JSON.stringify(allNodes));
            
            // 单击事件：高亮相关节点
            network.on("click", function (params) {
                if (params.nodes.length > 0) {
                    var selectedNode = params.nodes[0];
                    var connectedNodes = network.getConnectedNodes(selectedNode);
                    connectedNodes.push(selectedNode);
                    
                    var updateArray = [];
                    for (var i = 0; i < allNodes.length; i++) {
                        var node = allNodes[i];
                        if (connectedNodes.indexOf(node.id) !== -1) {
                            updateArray.push({id: node.id, hidden: false, opacity: 1.0});
                        } else {
                            updateArray.push({id: node.id, hidden: false, opacity: 0.1}); // 其他变暗
                        }
                    }
                    nodes.update(updateArray);
                } else {
                    // 点击空白处恢复
                    var updateArray = [];
                    for (var i = 0; i < allNodes.length; i++) {
                        updateArray.push({id: allNodes[i].id, hidden: false, opacity: 1.0});
                    }
                    nodes.update(updateArray);
                }
            });

            // 双击事件：仅保留该节点及其关联节点（隐藏其他）
            network.on("doubleClick", function (params) {
                if (params.nodes.length > 0) {
                    var selectedNode = params.nodes[0];
                    var connectedNodes = network.getConnectedNodes(selectedNode);
                    connectedNodes.push(selectedNode);
                    
                    var updateArray = [];
                    for (var i = 0; i < allNodes.length; i++) {
                        var node = allNodes[i];
                        if (connectedNodes.indexOf(node.id) !== -1) {
                            updateArray.push({id: node.id, hidden: false, opacity: 1.0});
                        } else {
                            updateArray.push({id: node.id, hidden: true}); // 彻底隐藏
                        }
                    }
                    nodes.update(updateArray);
                }
            });
        }
    }, 1000);
</script>
"""

# ==========================================
# 页面主逻辑
# ==========================================
def show_risk_page():
    st.markdown("<h2 style='text-align: center; color: #1f2d3d;'>场景风险推理</h2>", unsafe_allow_html=True)
    
    # 1. 加载推理引擎
    @st.cache_resource
    def load_risk_engine():
        return RiskInferenceEngine(data_dir="data")
    
    engine = load_risk_engine()
    elements_df = engine.scene_elements

    # 提取所有类别（维度）及其选项
    categories = elements_df['类别'].dropna().unique().tolist()
    options_dict = {cat: ["不选择"] + elements_df[elements_df['类别'] == cat]['场景要素'].dropna().tolist() for cat in categories}

    # 2. 初始化 Session State (用于控制下拉框的值)
    for cat in categories:
        if f"risk_select_{cat}" not in st.session_state:
            st.session_state[f"risk_select_{cat}"] = "不选择"

    # 随机生成按钮回调函数
    def randomize_selections():
        for cat in categories:
            # 随机挑选一个非“不选择”的有效要素
            valid_options = options_dict[cat][1:]
            if valid_options:
                st.session_state[f"risk_select_{cat}"] = random.choice(valid_options)

    # 3. 页面三栏布局: 左(输入) 中(图谱) 右(输出)
    # 稍微调宽了左侧列的比例(1.5)，以适应双列下拉框
    col_left, col_mid, col_right = st.columns([1.5, 2.3, 1.2], gap="medium")

    # ====================
    # 左侧：输入控制面板
    # ====================
    with col_left:
        st.markdown("#### ⚙️ 场景要素输入")
        st.button("🎲 随机场景模拟", on_click=randomize_selections, use_container_width=True)
        
        current_inputs = {}
        
        # 优化点：使用 2 列布局来放置下拉框，减少垂直高度
        input_col1, input_col2 = st.columns(2)
        
        for i, cat in enumerate(categories):
            # 按奇偶数将下拉框交替放入两列
            target_col = input_col1 if i % 2 == 0 else input_col2
            with target_col:
                current_inputs[cat] = st.selectbox(
                    label=cat,
                    options=options_dict[cat],
                    key=f"risk_select_{cat}"
                )
                
        do_infer = st.button("🚀 开始推理", type="primary", use_container_width=True)

    # ====================
    # 准备进行推理与展示
    # ====================
    if do_infer:
        # 判断是否全都没选
        if all(v == "不选择" for v in current_inputs.values()):
            st.warning("请至少选择一个有效的场景要素进行推理！")
            return

        # 调用引擎进行推理
        results, duration_sec = engine.infer(current_inputs)
        
        # 取出一个代表性的结果用于图谱展示
        rep_result = results[0]
        used_elements = [v for v in current_inputs.values() if v != "不选择"]

        # --------------------
        # 右侧：输出结果展示
        # --------------------
        with col_right:
            st.markdown("#### 📊 推理结果")
            st.info(f"⏱️ 本次推理用时: **{duration_sec:.4f} 秒**")
            
            # 模式 A & C：标准推理 或 均值填充 (只返回一条合并结果)
            if len(results) == 1:
                st.markdown(f"**推理模式**: `{rep_result['variant']}`")
                
                # 风险等级卡片
                risk_color = "#e74c3c" if "高" in rep_result['risk_level'] or "L3" in rep_result['risk_level'] else "#f39c12"
                st.markdown(f"""
                <div style="background-color: {risk_color}20; border-left: 5px solid {risk_color}; padding: 10px; border-radius: 5px; margin-bottom: 10px;">
                    <span style="color: #555; font-size: 14px;">风险等级</span><br>
                    <span style="color: {risk_color}; font-size: 24px; font-weight: bold;">{rep_result['risk_level']}</span>
                </div>
                """, unsafe_allow_html=True)
                
                # 事故类型卡片
                st.markdown(f"""
                <div style="background-color: #8e44ad20; border-left: 5px solid #8e44ad; padding: 10px; border-radius: 5px;">
                    <span style="color: #555; font-size: 14px;">最可能发生的事故类型</span><br>
                    <span style="color: #8e44ad; font-size: 22px; font-weight: bold;">{rep_result['accident_type']}</span>
                </div>
                """, unsafe_allow_html=True)

            # 模式 B：单要素缺失 (返回遍历列表)
            else:
                st.markdown("**推理模式**: `单要素缺失遍历`")
                st.markdown("系统已遍历该维度的所有可能情况：")
                
                # 组装成 DataFrame 展示
                df_res = pd.DataFrame(results)
                df_res = df_res[['variant', 'risk_level', 'accident_type']]
                df_res.columns = ['缺失假设', '风险等级', '事故类型']
                st.dataframe(df_res, use_container_width=True, hide_index=True)

        # --------------------
        # 中间：子图动态渲染
        # --------------------
        with col_mid:
            st.markdown("#### 🕸️ 场景关联图谱")
            st.caption("交互提示：**拖拽**移动节点，**单击**高亮关联节点，**双击**隔离并展示子图。")
            
            # 构建 NetworkX 子图
            sub_G = nx.DiGraph()
            center_node = "推理场景节点"
            sub_G.add_node(center_node, category='场景')
            
            # 添加输入的要素节点
            for elem in used_elements:
                cat = engine.element_to_category.get(elem, "未知")
                sub_G.add_node(elem, category=cat)
                sub_G.add_edge(elem, center_node) # 要素指向场景
                
            # 添加输出结果节点
            if len(results) == 1:
                risk_node = rep_result['risk_level']
                acc_node = rep_result['accident_type']
                sub_G.add_node(risk_node, category='风险等级')
                sub_G.add_node(acc_node, category='事故类型')
                sub_G.add_edge(center_node, risk_node)
                sub_G.add_edge(center_node, acc_node)
            else:
                # 单要素遍历时，把所有可能的结果都连上去，形成发散图
                for r in results:
                    r_node = r['risk_level']
                    a_node = r['accident_type']
                    sub_G.add_node(r_node, category='风险等级')
                    sub_G.add_node(a_node, category='事故类型')
                    sub_G.add_edge(center_node, r_node)
                    sub_G.add_edge(center_node, a_node)

            # 转换为 Pyvis
            net = Network(notebook=False, directed=True, height="600px", width="100%", bgcolor="#ffffff", font_color="#333333")
            net.from_nx(sub_G)
            
            # 设置颜色和大小
            for node in net.nodes:
                cat = sub_G.nodes[node['id']].get('category', '未知')
                node['color'] = get_color(cat)
                node['size'] = 30 if cat in ['场景', '风险等级', '事故类型'] else 15
                node['font'] = {'size': 16, 'face': 'Arial'}
                
            for edge in net.edges:
                edge['color'] = '#cccccc'

            # 物理引擎配置
            net.set_options("""
            var options = {
              "physics": {
                "enabled": true,
                "solver": "forceAtlas2Based",
                "forceAtlas2Based": { "gravitationalConstant": -50, "centralGravity": 0.01, "springLength": 100 }
              },
              "interaction": { "hover": true, "multiselect": true }
            }
            """)
            
            # 保存为 HTML 并注入交互 JS
            os.makedirs('./static', exist_ok=True)
            html_path = "./static/dynamic_sub_graph.html"
            net.save_graph(html_path)
            
            # 读取 HTML 并拼接 JS
            with open(html_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            
            # 将自定义 JS 插入到 </body> 前
            html_content = html_content.replace('</body>', CUSTOM_JS + '\n</body>')
            
            # 在 Streamlit 中渲染
            components.html(html_content, height=650)

    else:
        # 初始未点击推理时的占位展示
        with col_mid:
            st.markdown("#### 🕸️ 场景关联图谱")
            st.info("👈 请在左侧配置场景要素并点击「开始推理」，此处将动态生成图谱。")
            st.markdown("""
            <div style="height: 500px; border: 2px dashed #cccccc; border-radius: 10px; display: flex; align-items: center; justify-content: center; color: #aaa;">
                暂无数据
            </div>
            """, unsafe_allow_html=True)
            
        with col_right:
            st.markdown("#### 📊 推理结果")
            st.markdown("<div style='color: #aaa;'>等待推理...</div>", unsafe_allow_html=True)

if __name__ == "__main__":
    st.set_page_config(layout="wide")
    show_risk_page()