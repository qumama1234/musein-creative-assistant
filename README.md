# MuseIn Creative Assistant

一个管理多轮图片创作要求的本地原型。

用户不会每轮重新描述全部需求，通常只会说：

> 光线暖一点，其他不变。

这个项目负责维护“当前最终想要什么”，避免局部修改时丢失之前仍然有效的要求。

## 解决方案

```text
用户消息
  ↓
解析为候选修改 ChangeSet
  ↓
检查冲突
  ↓
成功：提交新状态并生成 Prompt
失败：保留上一版有效状态
```

系统将信息分成三类：

- **硬约束**：背景颜色、禁止文字、保持 Logo 等；
- **素材角色**：某张图用于主体、光影、背景还是风格；
- **开放创意**：例如“高级克制”“不要显得冰冷”，保留原文交给 LLM 发挥。

每项硬约束都会记录来源：

```text
user   用户明确要求
skill  Skill 提供的默认值
```

用户要求优先于 Skill。关闭 Skill 时，只删除仍然属于 Skill 的默认值。

## 关键行为

- 局部修改不会清空其他要求；
- 素材用途始终明确；
- 用户要求可以覆盖 Skill 默认值；
- 同一轮出现冲突时整轮拒绝；
- 失败操作不会破坏上一版状态；
- LLM 只负责理解语言，最终状态由确定性代码校验和提交。

## 运行 Demo

项目基础功能只需要 Python 3，无需数据库和 API Key。

```bash
cd /Users/xiangbinzeng/Desktop/musein-creative-assistant
python3 scripts/demo_creative_state.py
```

Demo 包含题目要求的完整会话：开启 Skill、两次局部修改、关闭 Skill，以及冲突操作。

## 运行单元测试

```bash
python3 -m unittest discover -s tests -v
```

当前结果：

```text
8/8 passed
```

## 使用 DeepSeek 测试自然语言解析

```bash
python3 -m pip install -r requirements-llm.txt
cp .env.example .env
python3 scripts/run_llm_adversarial.py
```

`.env`：

```env
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=replace-me
LLM_MODEL=deepseek-flash
```

项目包含 20 个预先冻结的攻击测试。预期答案不会发送给 LLM。

首次真实测试结果：

```text
18/20 passed
```

两个失败点被保留：

- “取消禁止文字”被解析成新增 `allowed`，而不是删除旧限制；
- “产品外观不变，但替换 Logo”没有返回合法 JSON，也暴露了父子级冲突问题。

## 项目结构

```text
app/creative_state.py              状态引擎
app/llm_parser.py                  LLM 解析适配器
config/                            Skill 配置
scripts/demo_creative_state.py     完整会话 Demo
scripts/run_llm_adversarial.py     LLM 对抗测试
tests/                             单元测试与 20 个攻击用例
reports/                           原始测试结果
docs/                              设计和风险说明
```

## 能力边界

当前项目保证的是：

```text
用户要求 → 当前状态 → Prompt
```

它不保证图片模型最终真的执行了每项要求。真实多轮生图还可能出现主体漂移、Logo 和文字失真、画质累计退化、局部编辑越界、参考图内容污染以及无法稳定复现等问题。

进一步说明：

- [设计与已知限制](docs/creative-state-design.md)
- [20 个对抗测试报告](docs/adversarial-test-report.md)
- [真实多轮生图风险](docs/real-world-image-risks.md)
