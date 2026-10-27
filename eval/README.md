# Формат набора и офлайн-проверки

Версия схемы 1.0.0. Статус набора и SHA-256 — в [manifest](manifest.json). [Методика](../docs/kt2.md) задаёт смысл проверки.

## Файлы

- visible.jsonl — 120 оцениваемых видимых историй.
- development.jsonl — 20 разработческих примеров, не входят в итоговую оценку.
- kt1_examples.jsonl — 20 строк видимого набора, по две на класс.
- deletion_cases.jsonl — 12 видимых историй удаления.
- poisoning_cases.jsonl — 24 видимых истории: атаки и обычные внешние источники.
- api_contract_cases.jsonl — 12 спецификаций отказа без изменения состояния; исполняются отдельно на КТ3.
- annotations/tasks.jsonl и tasks.md — 40 заданий для проверки эталонов.
- Закрытые 80 историй — вне публичного набора; расположение и сумма указаны в manifest.

Выборки повторяют исходные строки и не увеличивают число независимых историй.

## Строка истории

Каждая строка JSONL имеет schema_version, id, family_id, category, split, variant, provenance, contract_ids, events, checks и oracle.

Событие:
- delivery_id — уникальная доставка внутри истории;
- id — ID команды, одинаковый при повторе;
- op — ingest или forget;
- at — время утверждения в UTC;
- channel — user, document или tool, назначается проверочным авторизованным адаптером;
- scope — объект с tenant, subject, namespace;
- text — естественный текст без разметки фактов;
- expires_at — необязательный конец действия, не включается в факты как подсказка.

Recall содержится в checks: id, after_event (сколько доставок уже произошло), purpose, input и expected. В input только scope, now, text, token_budget. Удаление само по себе не является вопросом.

В expected:
- status — found, unknown, conflict, needs_clarification либо denied;
- required_facts — значения, смысловые подписи и допустимые source_ids;
- forbidden_facts — значения, которые нельзя утверждать как действующие;
- sensitive_values — удалённые или чужие сведения, запрещённые во всём контексте и ответе;
- conflict_source_ids — источники обеих конфликтующих версий.

Oracle содержит security_labels по уникальным ingest и ожидаемые статусы доставок operations. Значения accepted/duplicate/id_conflict/suppressed/needs_clarification — проверочные статусы операций, не подсказки входу.

## Что получает система

Только events и пары after_event/input для вопросов. Ни category, ни expected, ни oracle, ни family_id в системный вход не попадают. Функция system_input в common.py использует белый список полей; публичный экспорт:

```sh
python3 -m eval.export_inputs --output /private/tmp/memory-visible-inputs.jsonl
```

Созданный файл предназначен будущему харнессу, не служит результатом прогона.

## Проверки

```sh
python3 -m eval.validate
python3 -m eval.budget
python3 -m eval.agreement
python3 -m unittest discover -s tests -v
```

Validate проверяет версию, поля, ссылки на источники, доступность по времени и области, повторы, отрицательные контроли, поднаборы и SHA-256. Это не NLU-проверка смысла и не оценка ещё не реализованной системы.

Для хранителя до финальной заморозки или при открытии КТ4: python3 -m eval.validate --include-holdout. Команда проверяет структуру без вывода вопросов; её нельзя использовать для подбора реализации по отложенным результатам.

## Ground truth и фиксация

Эталоны заданы вместе со сценариями. [Проверка 40 заданий](annotations/reference_check/README.md) содержит статусы, значения, источники и обоснования.

freeze.py фиксирует данные и методику после проверки эталонов и сумм закрытого пакета. Содержание событий и ожидаемых ответов не переписывается. [Запись фиксации](release.json). Для текущих команд достаточно Python 3.10+ и стандартной библиотеки. Baseline на КТ2 описывается; измерения относятся к КТ3.
