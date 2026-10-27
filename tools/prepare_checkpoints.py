"""Build separate local CP-1/CP-2 snapshots and verify patches. Never writes Git metadata."""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from eval.common import digest, write_json

DEST = ROOT / "deliverables"
DENIED = (".eval_private/", ".future_kt3/", ".venv/", ".cache/", ".git/", "deliverables/",
          "eval/annotations/filled/", "eval/runs/")
DEFERRED = ("eval/baseline.py", "eval/score.py", "eval/tokenizer.py", "eval/requirements.txt",
            "eval/reports/baseline_context.json", "tests/test_baseline_and_score.py",
            "adr/001-memory-component.md")


def git(*args, cwd=ROOT):
    return subprocess.check_output(["git", *args], cwd=cwd)


def base_tree(ref):
    commit = git("rev-parse", "--verify", ref + "^{commit}").decode().strip()
    names = git("ls-tree", "-r", "--name-only", commit).decode().splitlines()
    return commit, {name: git("show", commit + ":" + name) for name in names}


def public_working_files():
    names = git("ls-files", "--cached", "--others", "--exclude-standard").decode().splitlines()
    result = {}
    for name in names:
        if name in DEFERRED or any(name.startswith(prefix) for prefix in DENIED):
            continue
        if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts:
            raise ValueError("Небезопасный путь в списке файлов.")
        path = ROOT / name
        if path.is_file():
            if path.is_symlink():
                raise ValueError("Ссылки не включаются в комплект автоматически: " + name)
            result[name] = path.read_bytes()
    return result


def section(text, number):
    match = re.search(r"^## " + str(number) + r"\..*?(?=^## |\Z)", text, re.M | re.S)
    if not match:
        raise ValueError("Не найден раздел " + str(number))
    return match.group().strip()


def kt1_snapshot(base, full):
    keep = [".gitignore", "LICENSE", "docs/kt1.md", "docs/sources.md",
            "adr.md", "eval/__init__.py", "eval/common.py",
            "eval/budget.py", "eval/budget_inputs.json", "eval/source_policy.json", "eval/kt1_examples.jsonl"]
    result = dict(base)
    result.update({name: full[name] for name in keep})
    main = full["design_doc.md"].decode()
    metrics = section(main, 7).split("| ID | Контракт |", 1)
    table = "| ID | Контракт |" + metrics[1].split("\n\n", 1)[0] if len(metrics) == 2 else ""
    title = ("# Сервис памяти как инфраструктура — КТ1\n\n"
             "Срез материалов КТ1, подготовлен 27.10.2026. Числа — цели и расчётные предположения; сервиса и измерений качества пока нет.\n\n"
             "Авторы материалов: Жбанов Артём Игоревич (БПМИ2411) и Савченко Владислав Евгеньевич (БПМИ2410). "
             "Оба совместно отвечают за КТ1 и КТ2 в равных долях — по 50%.\n\n"
             "[Краткая страница контракта и бюджетов](docs/kt1.md).\n\n")
    doc = title + "\n\n".join(section(main, n) for n in (1, 2, 3, 4))
    doc += ("\n\n## 5. Харнесс\n\nБудет подготовлен на следующих этапах; в КТ1 проверяются данные и расчёт бюджета.\n\n"
            "## 6. Память и состояние\n\nПредварительные правила приведены в контракте; реализация и испытания — КТ3.\n\n"
            "## 7. Первые проверочные истории\n\n"
            "20 историй, по две на класс: сохранение, изменение, время, конфликт, неизвестный ответ, длинный контекст, "
            "удаление, отравление, обычные внешние источники и изоляция/повтор. Это первые примеры будущего набора.\n\n"
            "[Данные](eval/kt1_examples.jsonl). Все факты вымышлены. Входы содержат события и вопросы; эталоны — отдельно "
            "в expected/oracle. Удаление проверяется до и после команды с контролем сохранности других сведений.\n\n")
    doc += table
    doc += ("\n\n## 8. Альтернатива\n\nПолная история с усечением по длине. Полное описание методики — задача КТ2; измерение — КТ3.\n\n"
            "## 9. Наблюдаемость\n\nПлан измерений и трейсинга уточняется на КТ3.\n\n")
    doc += section(main, 10)
    doc += ("\n\n## 11. Открытые вопросы\n\n"
            "| Вопрос | Владелец | Когда |\n|---|---|---|\n"
            "| Подтвердить сценарий и нагрузку | Артём и Владислав | До защиты |\n"
            "| Выбрать компонент, версию и доступную модель | Артём и Владислав | До КТ3 |\n"
            "| Подготовить полный набор и процедуру получения эталонов | Артём и Владислав | КТ2 |\n"
            "| Испытать удаление производных записей и конкуренцию | Артём и Владислав | КТ3 |\n\n"
            "[Источники](docs/sources.md).\n")
    result["design_doc.md"] = doc.encode()
    result["README.md"] = (
        "# Сервис памяти как инфраструктура — КТ1\n\n"
        "Тема 15 курса «Инженерия LLM-систем».\n\n"
        "[Основной документ](design_doc.md) · [Контракт и бюджеты](docs/kt1.md) · "
        "[20 историй](eval/kt1_examples.jsonl).\n\n"
        "Авторы материалов: Жбанов Артём Игоревич и Савченко Владислав Евгеньевич. "
        "Совместная ответственность за КТ1 и КТ2 — по 50%.\n\n"
        "Локальные проверки: python3 -m eval.validate и python3 -m eval.budget. "
        "Достаточно Python 3.10+, ключ API не нужен.\n\n"
        "Это срез КТ1: контракт, бюджеты, набросок схемы и первые примеры. "
        "Полный набор и методика КТ2 будут отдельным дополнением в CP-2.\n"
    ).encode()
    result["eval/README.md"] = (
        "# Первые 20 историй КТ1\n\n"
        "Файл kt1_examples.jsonl содержит события, контрольные вопросы и ожидаемое поведение. "
        "category и contract_ids связывают пример с контрактом. events — вход; checks.input — вопрос; "
        "checks.expected и oracle — данные проверяющего, которые нельзя передавать агенту.\n\n"
        "Во входе события: delivery_id, id, op, at, channel, scope, text и необязательный expires_at. "
        "Область scope состоит из tenant, subject, namespace. Канал назначает авторизованный адаптер.\n\n"
        "Проверка: python3 -m eval.validate. Смета: python3 -m eval.budget. "
        "Ни одна команда не вызывает модель. Значения качества пока не получены.\n"
    ).encode()
    result["docs/submission_checklist.md"] = (
        "# Проверка КТ1\n\n"
        "- [x] Клиент, сценарий, границы и нагрузка.\n"
        "- [x] Измеримый контракт и бюджеты с числами и допущениями.\n"
        "- [x] Альтернатива и её стоимость.\n"
        "- [x] 20 проверочных историй с ожидаемым поведением.\n"
        "- [x] Набросок схемы, риски и открытые вопросы.\n"
        "- [x] Материалы подготовлены и отредактированы; роли команды указаны.\n"
        "- [ ] Материалы вручную перенесены в CP-1, PR направлен в main, добавлен преподаватель и отправлена ссылка.\n\n"
        "[Основной документ](../design_doc.md).\n"
    ).encode()
    source = full["eval/validate.py"].decode().split("\ndef validate_dataset(", 1)[0]
    source += (
        "\n\ndef main():\n"
        "    manifest = json.loads((ROOT / 'eval/manifest.json').read_text())\n"
        "    for name, expected in manifest['public_sha256'].items():\n"
        "        require(digest(ROOT / 'eval' / name) == expected, 'Changed file: ' + name)\n"
        "    cases = read_jsonl(ROOT / 'eval/kt1_examples.jsonl')\n"
        "    require(len(cases) == 20 and len({c['id'] for c in cases}) == 20, 'Expected 20 stories')\n"
        "    require(Counter(c['category'] for c in cases) == {c: 2 for c in CATEGORIES}, 'Category counts')\n"
        "    policy = json.loads((ROOT / 'eval/source_policy.json').read_text())\n"
        "    for case in cases: validate_case(case, policy)\n"
        "    print(json.dumps({'checkpoint': 'CP-1', 'stories': 20, 'status': 'valid_data_not_service_results'}))\n\n"
        "if __name__ == '__main__':\n    main()\n"
    )
    result["eval/validate.py"] = source.encode()
    manifest = {"checkpoint": "CP-1", "dataset_version": "kt1-20-v1", "stories": 20,
                "public_sha256": {p.removeprefix("eval/"): hashlib.sha256(result[p]).hexdigest()
                                  for p in ("eval/kt1_examples.jsonl", "eval/source_policy.json", "eval/budget_inputs.json")}}
    result["eval/manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
    return result


def patch(before, after):
    parts = []
    for name in sorted(before.keys() | after.keys()):
        old, new = before.get(name), after.get(name)
        if old == new:
            continue
        parts.append("diff --git a/" + name + " b/" + name + "\n")
        if old is None:
            parts.append("new file mode 100644\n")
        if new is None:
            parts.append("deleted file mode 100644\n")
        lines = difflib.unified_diff(
            old.decode().splitlines(keepends=True) if old is not None else [],
            new.decode().splitlines(keepends=True) if new is not None else [],
            fromfile="a/" + name if old is not None else "/dev/null",
            tofile="b/" + name if new is not None else "/dev/null")
        for line in lines:
            parts.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    return "".join(parts)


def write_tree(folder, tree):
    folder.mkdir(parents=True, exist_ok=True)
    existing = {p.relative_to(folder).as_posix(): p for p in folder.rglob("*") if p.is_file()}
    for name, path in existing.items():
        if name not in tree:
            path.unlink()
    for name, content in tree.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def verify(base, one, two, p1, p2):
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        write_tree(folder, base)
        for patch_path, expected in ((p1, one), (p2, two)):
            subprocess.run(["git", "apply", "--check", str(patch_path)], cwd=folder, check=True, capture_output=True)
            subprocess.run(["git", "apply", str(patch_path)], cwd=folder, check=True, capture_output=True)
            actual = {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}
            if actual != expected:
                raise ValueError("Патч не воспроизводит ожидаемый срез.")
        subprocess.run([sys.executable, "-m", "eval.validate"], cwd=folder, check=True, capture_output=True)
        write_tree(folder, one)
        subprocess.run([sys.executable, "-m", "eval.validate"], cwd=folder, check=True, capture_output=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/CP-1")
    args = parser.parse_args()
    commit, base = base_tree(args.base)
    full = public_working_files()
    # Preserve unchanged files inherited from CP-1, including its original topics.md.
    two = {**base, **full}
    one = kt1_snapshot(base, full)
    DEST.mkdir(exist_ok=True)
    p1, p2 = DEST / "01-CP-1.patch", DEST / "02-CP-2.patch"
    p1.write_text(patch(base, one))
    p2.write_text(patch(one, two))
    verify(base, one, two, p1, p2)
    for name, tree in (("CP-1", one), ("CP-2", two)):
        if any(any(p.startswith(prefix) for prefix in DENIED) for p in tree):
            raise ValueError("В комплект попали закрытые или локальные файлы.")
        if any(p in DEFERRED for p in tree):
            raise ValueError("В комплект КТ1–КТ2 попали отложенные заготовки КТ3.")
        write_tree(DEST / name, tree)
        with zipfile.ZipFile(DEST / (name + ".zip"), "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path, data in sorted(tree.items()):
                archive.writestr(path, data)
    dataset_manifest = json.loads(full["eval/manifest.json"])
    status = dataset_manifest["freeze_status"]
    report = {"prepared_at": "2026-10-27", "base_ref": args.base, "base_commit": commit,
              "CP-1": {"files": len(one), "zip_sha256": digest(DEST / "CP-1.zip")},
              "CP-2": {"files": len(two), "zip_sha256": digest(DEST / "CP-2.zip"), "freeze_status": status,
                       "pr_ready": status == "frozen", "ground_truth": dataset_manifest.get("ground_truth", {}).get("method")},
              "patches_reproduce_both_snapshots": True, "both_snapshot_validators_passed": True,
              "private_files_excluded": True, "deferred_KT3_files_excluded": True,
              "scope": "KT1_KT2_only", "git_metadata_changed": False, "github_writes": 0}
    write_json(DEST / "manifest.json", report)
    fence = chr(96) * 3
    q1, q2 = shlex.quote(str(p1)), shlex.quote(str(p2))
    guide = (
        "# Ручной перенос CP-1 и CP-2\n\n"
        "Это локальные срезы файлов, не созданные ветки. Публикация выполняется вами вручную после готовности материалов.\n\n"
        "CP-1 содержит контракт, бюджеты и 20 историй. CP-2 добавляет полный набор, методику, разметку и фиксацию. "
        "Общие документы имеют отдельные версии; второй патч содержит только дополнение к первому.\n\n"
        "Текущий статус CP-2: " + status + ". Эталоны заданы вместе со сценариями; "
        "комплекты проверки распределены 20/20. "
        "Тексты PR находятся в PR_CP-1.md и PR_CP-2.md.\n\n"
        "## До переноса\n\n"
        "Сохраните рабочую папку и закрытую копию .eval_private отдельно. "
        "Архивы CP-1.zip/CP-2.zip и патчи не содержат отложенных данных, личных бланков, окружения и заготовок КТ3.\n\n"
        "Патч CP-1 подготовлен относительно локального " + args.base + ", commit " + commit + ". "
        "Если удалённая ветка изменилась, сначала проверяем применимость; команд принудительного обновления здесь нет.\n\n"
        "## Чистая копия для публикации\n\n"
        "Ниже команды для ручного запуска. "
        "Отдельная чистая копия позволяет сохранить текущую локальную работу.\n\n"
        + fence + "sh\n"
        "git clone https://github.com/et2439/hse-llm-SE-memory-service-as-infrastructure.git memory-service-publish\n"
        "cd memory-service-publish\n"
        "git switch CP-1\n"
        "git apply --check " + q1 + "\n"
        "git apply " + q1 + "\n"
        "python3 -m eval.validate\n"
        "git add .\n"
        "git commit -m \"КТ1: контракт, бюджеты и 20 проверочных историй\"\n"
        "git push origin CP-1\n"
        + fence + "\n\n"
        "Затем вручную проверьте PR CP-1 → main. Для КТ2:\n\n"
        + fence + "sh\n"
        "git switch -c CP-2\n"
        "git apply --check " + q2 + "\n"
        "git apply " + q2 + "\n"
        "python3 -m eval.validate\n"
        "git add .\n"
        "git commit -m \"КТ2: набор, ground truth по конструкции и методика оценки\"\n"
        "git push -u origin CP-2\n"
        + fence + "\n\n"
        "PR для CP-2 направьте сначала в CP-1, чтобы показывались только изменения КТ2. "
        "После принятия CP-1 при необходимости перенесём дополнение CP-2 поверх обновлённой main. "
        "Если CP-2 уже существует, используйте её вместо создания новой ветки и сначала проверим её состояние.\n\n"
        "Даты и авторство коммитов остаются фактическими. Архивы можно использовать для просмотра и ручного копирования "
        "вместо патчей; добавлять закрытую папку на GitHub не требуется.\n\n"
        "Для сдачи каждой КТ добавьте преподавателя в ревьюеры соответствующего PR/MR и отправьте ссылку в форму курса. "
        "В КТ2 укажите версию набора и методики оценки. "
        "Закрытый пакет передавайте отдельно; его внешняя передача пока не подтверждена. "
        "Порядок досдачи согласуйте с преподавателем. "
        "[Правила курса](https://github.com/xufana/llm-system-engineering/blob/main/project.md).\n"
    )
    (DEST / "TRANSFER.md").write_text(guide)
    (DEST / "PR_CP-1.md").write_text(
        "# КТ1: контракт, бюджеты и первые проверочные истории\n\n"
        "От команды: Жбанов Артём Игоревич (БПМИ2411), Савченко Владислав Евгеньевич (БПМИ2410). "
        "Оба совместно отвечаем за КТ1 и КТ2 в равных долях — по 50%.\n\n"
        "Подготовили описание сервиса памяти для внешнего LLM-агента: актуальные сведения с источниками, "
        "обновление, забывание, изоляция и ограничение контекста. Зафиксировали клиента, границы, "
        "численные бюджеты и стоимость альтернативы с усечённой историей.\n\n"
        "Материалы: docs/kt1.md — краткая страница; design_doc.md — контракт, расчёты, схема, "
        "риски и открытые вопросы; eval/kt1_examples.jsonl — 20 историй с контрольными вопросами.\n\n"
        "Проверка: python3 -m eval.validate; python3 -m eval.budget. Срез и его патч проверены локально. "
        "Задержка и качество — цели, расходы — расчётные предположения. Реализация сервиса не входит в эту КТ.\n"
    )
    (DEST / "PR_CP-2.md").write_text(
        "# КТ2: набор и методика оценки сервиса памяти\n\n"
        "От команды: Жбанов Артём Игоревич (БПМИ2411), Савченко Владислав Евгеньевич (БПМИ2410). "
        "Оба совместно отвечаем за КТ1 и КТ2 в равных долях — по 50%; комплекты проверки закреплены поровну, по 20 заданий.\n\n"
        "Подготовили полный набор до реализации сервиса: 200 историй в десяти классах, "
        "120 видимых и 80 отложенных до КТ4; отдельно 20 разработческих примеров. "
        "Связали метрики с контрактом, описали правила проверки, baseline и порядок усложнений.\n\n"
        "Эталоны заданы вместе с синтетическими историями. Дополнительная проверка "
        "охватила 40 вопросов; комплекты распределены по 20 между ответственными. "
        "Правила задания эталонов и ограничения набора описаны в docs/kt2.md.\n\n"
        "Набор и методика зафиксированы: eval/manifest.json, eval/protocol.json и eval/release.json. "
        "Закрытая часть исключена из Git и публичного комплекта; внешний факт передачи не заявляется.\n\n"
        "Проверка: python3 -m eval.validate; python3 -m eval.budget; "
        "python3 -m unittest discover -s tests -v. Оба среза и последовательные патчи проверены локально. "
        "Сервис, модельные прогоны и измеренный baseline относятся к КТ3.\n"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
