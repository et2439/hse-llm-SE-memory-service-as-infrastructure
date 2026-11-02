# Основания и источники

| Источник | Как используется |
|---|---|
| [Требования проекта курса](https://github.com/xufana/llm-system-engineering/blob/main/project.md) | Клиент, контракт, численные бюджеты, архитектурный набросок и первые примеры |
| [Тема 15](https://github.com/xufana/llm-system-engineering/blob/main/topics.md) | Инфраструктура памяти, удаление, отравление, контекст и baseline |
| [Исходный шаблон](https://github.com/xufana/llm-system-engineering/blob/main/templates/design_doc_template.md) | Форма контракта, бюджетов, eval и решений |
| [Ревью другой команды](https://github.com/CHA-llm-memory-team/memory-service/pull/1#issuecomment-6309849383) | Пример требований к ясности документа, удалению по контракту клиента и отрицательным контролям |
| [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna) | Ценовой сценарий Standard: $0,10/$0,50 за миллион input/output |
| [text-embedding-3-small](https://developers.openai.com/api/docs/models/text-embedding-3-small) | Ценовой сценарий embeddings: $0,02 за миллион input |
| [Mem0 OSS REST](https://github.com/mem0ai/mem0/blob/main/docs/open-source/features/rest-api.mdx) | Наличие готовых операций добавления, поиска, обновления и удаления; API OSS отличается от платформы |
| [Mem0 delete](https://github.com/mem0ai/mem0/blob/main/docs/core-concepts/memory-operations/delete.mdx) | Удаление по ID/области не равно доказанной очистке наших производных записей |
| [Graphiti](https://help.getzep.com/graphiti/getting-started/welcome) | Альтернатива с временным графом |
| [Letta](https://docs.letta.com/v1-sdk/concepts/stateful-agents) | Альтернатива с состоянием агента и управлением памятью |

Смета использует тарифный сценарий и допущения из [budget_inputs.json](../eval/budget_inputs.json). Инфраструктура, нагрузка, число вызовов и токенов — плановые значения; доступность API и совместимость компонентов требуют проверки.
