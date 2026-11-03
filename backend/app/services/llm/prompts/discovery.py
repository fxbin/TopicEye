"""关系发现与话题命名模板；从原业务构造器原样提取。"""

RELATION_USER_TEMPLATE = '你是内容关联分析师。判断以下目标内容与每条候选内容的关系类型。\n\n关系类型：\n- causal: 目标是候选的原因/背景，或反过来（A 事件导致 B 发生）\n- response: 候选是对目标的回应、评论、观点输出\n- contrast: 候选与目标观点对立或呈现不同角度\n- none: 无明显关联\n\n目标内容：[{target_id}] {title} — {summary}\n\n候选内容：\n{candidates}\n\n只输出有关系（非 none）的，返回JSON：\n[{{"target_id": 123, "type": "causal", "confidence": 0.8, "reason": "简述依据"}}]\n规则：confidence 取 0.5-1.0；reason 不超过 30 字；没有关联返回空数组 []'

TOPIC_CLUSTER_SYSTEM = "你是一个话题命名助手。根据多篇内容标题和标签，生成自然、准确的话题名称。\n\n命名规则：\n- 话题名必须是自然语言短语，不要用顿号/逗号拼接关键词\n- 6-15字，概括核心主题而非罗列标签\n- 优先提炼技术/产品/事件名称，避免使用动词\n- 好例子：'大模型上下文缓存优化'、'宇树人形机器人量产'、'arXiv论文精选'\n- 坏例子：'AI、模型'、'推出、发布'、'parser、pricing'\n"

TOPIC_CLUSTER_USER_TEMPLATE = '以下是同一话题的多篇内容标题：\n{titles}\n\n关键标签：{tags}\n\n请为这个话题生成：\n1. 话题名称（自然语言，6-15字）\n2. 一句话摘要（20字以内）\n\n返回JSON：{{"name": "话题名", "summary": "一句话"}}'
