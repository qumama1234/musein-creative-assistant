# Adversarial LLM test report

## Frozen-run protocol

- The 20 cases and their assertions were written before the first LLM call.
- Expected results were not included in the model request.
- The model received only the current synthetic state, the synthetic user
  message, and the JSON output protocol.
- Cases were not edited after failures.
- The runner exits non-zero when any case fails.

## First run

- Model: `deepseek-flash`
- Endpoint: official DeepSeek OpenAI-compatible API
- Result: **18/20 passed**
- Full machine-readable output: `reports/llm-adversarial-latest.json`

## Failures retained

### A11 — removing a previous prohibition

Input: `现在允许加文字了，把之前禁止新增文字的限制取消。`

The model emitted `text.addition=allowed`. The frozen expectation required a
`remove` operation so the previous prohibition disappeared instead of being
replaced by a new hard requirement. This reveals an unresolved product semantic:
whether “allowed” is explicit state or merely the absence of “forbidden”.

### A19 — parent/child semantic conflict

Input: `产品外观全部保持不变，但把原来的 Logo 换成一个新的圆形 Logo。`

The model did not return a parseable JSON object. Even with output instructions,
structured generation can fail. The case also attacks a deeper limitation: the
deterministic engine detects two values on the same exact path, but does not yet
understand that preserving a parent object can conflict with changing a child
attribute such as its logo.

## What the score does not prove

The 18 passing cases are a useful first attack set, not a reliability claim.
They do not measure repeated-run variance, unseen paraphrases, long histories,
multiple Skills, image-result verification, or adversarial inputs in other
languages. A serious evaluation should add repeated trials and a held-out set
created independently of the parser prompt.
