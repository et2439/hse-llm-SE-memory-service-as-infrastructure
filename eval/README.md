# Первые 20 историй КТ1

Файл kt1_examples.jsonl содержит события, контрольные вопросы и ожидаемое поведение. category и contract_ids связывают пример с контрактом. events — вход; checks.input — вопрос; checks.expected и oracle — данные проверяющего, которые нельзя передавать агенту.

Во входе события: delivery_id, id, op, at, channel, scope, text и необязательный expires_at. Область scope состоит из tenant, subject, namespace. Канал назначает авторизованный адаптер.

Проверка: python3 -m eval.validate. Смета: python3 -m eval.budget. Ни одна команда не вызывает модель. Значения качества пока не получены.
