# Основания и источники

Проверено 25.10.2026. Предложения и численные допущения команды отделены от утверждений источников.

| Источник | Как используется |
|---|---|
| [Требования проекта курса](https://github.com/xufana/llm-system-engineering/blob/main/project.md) | Состав КТ1–КТ2, порядок сдачи, разделение набора и последующие этапы |
| [Тема 15](https://github.com/xufana/llm-system-engineering/blob/main/topics.md) | Инфраструктура памяти, удаление, отравление, контекст и baseline |
| [Исходный шаблон](https://github.com/xufana/llm-system-engineering/blob/main/templates/design_doc_template.md) | Форма контракта, бюджетов, eval и решений |
| [Ревью другой команды](https://github.com/CHA-llm-memory-team/memory-service/pull/1#issuecomment-6309849383) | Пример требований к ясности документа, удалению по контракту клиента и отрицательным контролям; не источник наших данных |
| [Материалы КТ2 другой команды, фиксированная версия](https://github.com/CHA-llm-memory-team/memory-service/tree/dfcd3a72f0e8a8f50a459a1050ec42b5e4158cae) | Пример разделения данных, протокола разметки и разбора ошибок; наш набор и код не копировались |
| [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna) | Ценовой сценарий Standard: $0,10/$0,50 за миллион input/output |
| [text-embedding-3-small](https://developers.openai.com/api/docs/models/text-embedding-3-small) | Ценовой сценарий embeddings: $0,02 за миллион input |
| [Mem0 OSS REST](https://github.com/mem0ai/mem0/blob/main/docs/open-source/features/rest-api.mdx) | Наличие готовых операций добавления, поиска, обновления и удаления; API OSS отличается от платформы |
| [Mem0 delete](https://github.com/mem0ai/mem0/blob/main/docs/core-concepts/memory-operations/delete.mdx) | Удаление по ID/области не равно доказанной очистке наших производных записей |
| [Graphiti](https://help.getzep.com/graphiti/getting-started/welcome) | Альтернатива с временным графом |
| [Letta](https://docs.letta.com/v1-sdk/concepts/stateful-agents) | Альтернатива с состоянием агента и управлением памятью |

Тарифы не подтверждают доступ к API из аккаунта команды. Цены инфраструктуры, нагрузка, число вызовов и токенов — наши плановые допущения в budget_inputs.json. Сравнительные преимущества компонентов без прогона не заявляются.

Повторно сверено 27.10.2026: на КТ2 baseline описывается, измерения и общий стенд относятся к КТ3. В методике для бюджета памяти выбрана единица cl100k_base; реализация подсчёта и проверка доступности модели относятся к следующему этапу. Платные API не вызывались.

