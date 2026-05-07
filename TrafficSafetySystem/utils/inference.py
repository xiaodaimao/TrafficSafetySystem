import torch
import torch.nn as nn
import torch.nn.functional as F
import dgl
import pandas as pd
import numpy as np
import time
import os
import json

# ==========================================
# 1. 模型定义 (完整复用 app.py 中的 R-GCN)
# ==========================================
class RGCN(nn.Module):
    def __init__(self, num_nodes, h_dim, num_rels):
        super().__init__()
        self.emb = nn.Embedding(num_nodes, h_dim)
        self.conv1 = dgl.nn.RelGraphConv(
            h_dim, h_dim, num_rels, regularizer="bdd", num_bases=100, self_loop=True
        )
        self.conv2 = dgl.nn.RelGraphConv(
            h_dim, h_dim, num_rels, regularizer="bdd", num_bases=100, self_loop=True
        )
        self.dropout = nn.Dropout(0.2)

    def forward(self, g, nids):
        x = self.emb(nids)
        h = F.relu(self.conv1(g, x, g.edata[dgl.ETYPE], g.edata.get('norm')))
        h = self.dropout(h)
        h = self.conv2(g, h, g.edata[dgl.ETYPE], g.edata.get('norm'))
        return self.dropout(h)

class LinkPredict(nn.Module):
    def __init__(self, num_nodes, num_rels, h_dim=500, reg_param=0.01):
        super().__init__()
        self.rgcn = RGCN(num_nodes, h_dim, num_rels * 2)
        self.reg_param = reg_param
        self.w_relation = nn.Parameter(torch.Tensor(num_rels, h_dim))
        nn.init.xavier_uniform_(self.w_relation, gain=nn.init.calculate_gain("relu"))

    def calc_score(self, embedding, triplets):
        s = embedding[triplets[:, 0]]
        r = self.w_relation[triplets[:, 1]]
        o = embedding[triplets[:, 2]]
        score = torch.sum(s * r * o, dim=1)
        return score

    def forward(self, g, nids):
        return self.rgcn(g, nids)

# ==========================================
# 2. 风险推理引擎
# ==========================================
class RiskInferenceEngine:
    def __init__(self, data_dir):
        """
        初始化引擎，加载模型和映射
        """
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
        # 1. 加载映射文件 (更新为读取 .json 文件)
        self.entity_map = self._load_map(os.path.join(data_dir, "kg_entities.json"))
        self.relation_map = self._load_map(os.path.join(data_dir, "kg_relations.json"))
        self.entity_map_inv = {v: k for k, v in self.entity_map.items()}
        
        # 2. 加载场景要素表
        self.scene_elements = pd.read_excel(os.path.join(data_dir, "scene_elements.xlsx"))
        self.element_to_category = dict(zip(self.scene_elements['场景要素'], self.scene_elements['类别']))
        
        # 预先提取关键节点的 ID 集合 (用于张量加速运算)
        self.scene_ids = [k for k, v in self.entity_map_inv.items() if str(v).startswith("场景")]
        self.risk_ids = [k for k, v in self.entity_map_inv.items() if v in ["L0", "L1", "L2", "L3"]]
        self.accident_ids = [k for k, v in self.entity_map_inv.items() if v in ["追尾事故", "车辆起火", "撞固定物", "撞抛洒物", "翻车事故"]]
        
        # 3. 加载图结构
        self.g = dgl.load_graphs(os.path.join(data_dir, "kg_graph.bin"))[0][0].to(self.device)
        
        # 4. 初始化模型并加载权重
        num_nodes = len(self.entity_map)
        num_rels = len(self.relation_map)
        self.model = LinkPredict(num_nodes=num_nodes, num_rels=num_rels).to(self.device)
        checkpoint = torch.load(os.path.join(data_dir, "model_weight.pth"), map_location=self.device)
        self.model.load_state_dict(checkpoint["state_dict"])
        self.model.eval()

    def _load_map(self, path):
        """加载 JSON 格式的映射文件"""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # 确保 value 是 int 类型，以防 json 解析为 string
        return {str(k): int(v) for k, v in data.items()}

    def infer(self, input_dict):
        """
        统一的推理接口
        :param input_dict: 字典形式的前端输入，例如：{'天气': '晴天', '能见度': '不选择', '时间': '夜晚'}
        :return: (结果列表, 推理总耗时)
        """
        start_time = time.time()
        
        valid_elements = [v for k, v in input_dict.items() if v != "不选择"]
        missing_dims = [k for k, v in input_dict.items() if v == "不选择"]

        if len(missing_dims) == 0:
            # 逻辑 A：没有缺失要素，标准推理
            res = self._core_inference(valid_elements)
            res['variant'] = "标准推理 (要素完整)"
            duration = time.time() - start_time
            return [res], duration

        elif len(missing_dims) == 1:
            # 逻辑 B：单要素缺失，遍历所有可能的选项
            dim = missing_dims[0]
            options = self.scene_elements[self.scene_elements['类别'] == dim]['场景要素'].dropna().tolist()
            results = []
            for opt in options:
                temp_elements = valid_elements + [opt]
                res = self._core_inference(temp_elements)
                res['variant'] = f"单要素缺失 ({dim}) 假设为: {opt}"
                results.append(res)
            
            duration = time.time() - start_time
            return results, duration

        else:
            # 逻辑 C：多要素缺失，Mean-Embedding 模糊推理
            res = self._core_inference_mean_embedding(valid_elements, missing_dims)
            res['variant'] = f"模糊推理 (缺失维度: {', '.join(missing_dims)})"
            duration = time.time() - start_time
            return [res], duration

    def _core_inference(self, elements):
        """
        标准图推理计算 (张量优化版)
        """
        with torch.no_grad():
            all_nodes = torch.arange(self.g.num_nodes(), device=self.device)
            embedding = self.model(self.g, all_nodes)
            
            # 1. 场景匹配打分
            scene_scores = torch.zeros(len(self.scene_ids), device=self.device)
            scene_ids_tensor = torch.tensor(self.scene_ids, device=self.device)
            o_scene = embedding[scene_ids_tensor] # [num_scenes, h_dim]
            
            for element in elements:
                category = self.element_to_category[element]
                head_id = self.entity_map[element]
                relation_id = self.relation_map[category]
                
                s = embedding[head_id].unsqueeze(0) # [1, h_dim]
                r = self.model.w_relation[relation_id].unsqueeze(0) # [1, h_dim]
                
                # 计算当前要素与所有场景节点的得分
                scores = torch.sum(s * r * o_scene, dim=1) 
                scene_scores += scores
            
            # 获取得分最高的场景 ID
            best_scene_idx = torch.argmax(scene_scores).item()
            best_scene_id = self.scene_ids[best_scene_idx]
            
            # 2. 推理该场景的风险等级
            risk_rel_id = self.relation_map["risk_level"]
            s_scene = embedding[best_scene_id].unsqueeze(0)
            r_risk = self.model.w_relation[risk_rel_id].unsqueeze(0)
            o_risk = embedding[torch.tensor(self.risk_ids, device=self.device)]
            risk_scores = torch.sum(s_scene * r_risk * o_risk, dim=1)
            best_risk_name = self.entity_map_inv[self.risk_ids[torch.argmax(risk_scores).item()]]
            
            # 3. 推理该场景的事故类型
            acc_rel_id = self.relation_map["最可能发生的事件小类"]
            r_acc = self.model.w_relation[acc_rel_id].unsqueeze(0)
            o_acc = embedding[torch.tensor(self.accident_ids, device=self.device)]
            acc_scores = torch.sum(s_scene * r_acc * o_acc, dim=1)
            best_acc_name = self.entity_map_inv[self.accident_ids[torch.argmax(acc_scores).item()]]

            return {
                "risk_level": best_risk_name,
                "accident_type": best_acc_name,
                "elements_used": elements
            }

    def _core_inference_mean_embedding(self, valid_elements, missing_dims):
        """
        均值填充 (Mean-Embedding) 推理逻辑
        对于缺失维度，提取该类别下所有实体的 Embedding 计算平均值，替代原本单一确定的实体向量。
        """
        with torch.no_grad():
            all_nodes = torch.arange(self.g.num_nodes(), device=self.device)
            embedding = self.model(self.g, all_nodes)
            
            scene_scores = torch.zeros(len(self.scene_ids), device=self.device)
            scene_ids_tensor = torch.tensor(self.scene_ids, device=self.device)
            o_scene = embedding[scene_ids_tensor]
            
            # 1. 计算已知明确要素的得分
            for element in valid_elements:
                category = self.element_to_category[element]
                head_id = self.entity_map[element]
                relation_id = self.relation_map[category]
                
                s = embedding[head_id].unsqueeze(0)
                r = self.model.w_relation[relation_id].unsqueeze(0)
                scores = torch.sum(s * r * o_scene, dim=1)
                scene_scores += scores
                
            # 2. 计算缺失维度的 Mean-Embedding 得分
            for dim in missing_dims:
                options = self.scene_elements[self.scene_elements['类别'] == dim]['场景要素'].dropna().tolist()
                cand_ids = [self.entity_map[opt] for opt in options if opt in self.entity_map]
                
                if not cand_ids:
                    continue
                    
                cand_ids_tensor = torch.tensor(cand_ids, device=self.device)
                # ★ 核心逻辑：对该维度所有合法实体的向量取平均 ★
                s_mean = torch.mean(embedding[cand_ids_tensor], dim=0, keepdim=True) 
                
                relation_id = self.relation_map.get(dim)
                if relation_id is None:
                    continue
                r = self.model.w_relation[relation_id].unsqueeze(0)
                
                # 用均值向量进行场景评分
                scores = torch.sum(s_mean * r * o_scene, dim=1)
                scene_scores += scores
            
            # 获取最高得分场景
            best_scene_idx = torch.argmax(scene_scores).item()
            best_scene_id = self.scene_ids[best_scene_idx]
            
            # 3. 推理风险等级
            risk_rel_id = self.relation_map["risk_level"]
            s_scene = embedding[best_scene_id].unsqueeze(0)
            r_risk = self.model.w_relation[risk_rel_id].unsqueeze(0)
            o_risk = embedding[torch.tensor(self.risk_ids, device=self.device)]
            risk_scores = torch.sum(s_scene * r_risk * o_risk, dim=1)
            best_risk_name = self.entity_map_inv[self.risk_ids[torch.argmax(risk_scores).item()]]
            
            # 4. 推理事故类型
            acc_rel_id = self.relation_map["最可能发生的事件小类"]
            r_acc = self.model.w_relation[acc_rel_id].unsqueeze(0)
            o_acc = embedding[torch.tensor(self.accident_ids, device=self.device)]
            acc_scores = torch.sum(s_scene * r_acc * o_acc, dim=1)
            best_acc_name = self.entity_map_inv[self.accident_ids[torch.argmax(acc_scores).item()]]

            return {
                "risk_level": best_risk_name,
                "accident_type": best_acc_name,
                "elements_used": valid_elements + ["(Mean-Embedding)"]
            }