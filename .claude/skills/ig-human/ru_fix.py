#!/usr/bin/env python3
"""
ru_fix.py - [ru] автоматическая правка русских штампов и канцелярита без поломки грамматики.

Принцип: каждое правило либо гарантированно сохраняет грамматику (замена на
конструкцию с тем же падежом или согласование через морфологию pymorphy3),
либо не срабатывает. Текст, который правило не может безопасно исправить,
остаётся как был - он и так грамматически верный. Ручная правка не нужна.

Что делает:
  - удаляет предложения целиком, если это дежурный призыв ("Подписывайтесь...",
    "Ставь лайк, если...") - удаление целого предложения не ломает соседние;
  - заменяет штампы на нейтральные конструкции с тем же управлением
    ("на сегодняшний день" -> "на сегодня", "важно отметить, что" -> "важно, что");
  - с морфологией (pip install pymorphy3):
      "является ключевым инструментом" -> "- ключевой инструмент"
      "являлся частью"                 -> "был частью"
      "данного проекта"                -> "этого проекта"  (только если согласуется)
      "в связи с ростом цен"           -> "из-за роста цен"
      "осуществляет продажи"           -> "проводит продажи"
      "с целью увеличить"              -> "чтобы увеличить", "с целью роста" -> "для роста"
Без pymorphy3 морфологические правила просто пропускаются.

Usage
  python3 ru_fix.py draft.txt
"""

import re
import sys

try:
    import pymorphy3
    MORPH = pymorphy3.MorphAnalyzer()
except Exception:  # noqa: BLE001 - без словаря работают только безопасные замены
    MORPH = None

CYR = "А-Яа-яЁё"
WORD_RE = re.compile(rf"[{CYR}]+(?:-[{CYR}]+)?")

# Дежурные призывы: предложение с ними удаляется целиком.
BAIT_RE = re.compile(
    r"(?i)^\s*(?:подписыва(?:йся|йтесь)|подпиш(?:ись|итесь)|ставь(?:те)? лайк|жми(?:те)? на колокольчик"
    r"|не забудь(?:те)? подписаться|лайк,? если)\b")

# Замены, которые не меняют управление (падеж следующего слова остаётся верным).
SAFE = [
    (re.compile(r"(?i)\bдавайте (разбер[её]мся)\b"), lambda m: "разберёмся"),
    (re.compile(r"(?i)\b(?:ни для кого |уже )?не секрет,\s*что\b"), lambda m: "очевидно, что"),
    (re.compile(r"(?i)\b(?:важно|стоит|хочется|хочу) отметить,\s*что\b"), lambda m: "важно, что"),
    (re.compile(r"(?i)\bна сегодняшний день\b"), lambda m: "на сегодня"),
    (re.compile(r"(?i)\bв данный момент\b"), lambda m: "сейчас"),
    (re.compile(r"(?i)\bпосредством\b"), lambda m: "с помощью"),
]

PAST_YAVL = {"являлся": "был", "являлась": "была", "являлось": "было", "являлись": "были"}
DANN_SING = {"данный", "данного", "данному", "данном", "данная", "данной", "данную", "данною", "данное"}
NP_POS = {"ADJF", "PRTF", "NOUN", "NUMR", "NPRO"}


def _keep_case(src, repl):
    if src[:1].isupper():
        return repl[:1].upper() + repl[1:]
    return repl


def _parses(word, case=None):
    if MORPH is None:
        return []
    ps = MORPH.parse(word)
    return [p for p in ps if case is None or case in p.tag]


def _collect_np(words, start, case):
    """Подряд идущие слова в нужном падеже: прилагательные/причастия, затем существительное."""
    out = []
    for i in range(start, len(words)):
        w = words[i]
        ps = [p for p in _parses(w.group(0), case) if p.tag.POS in NP_POS]
        if not ps:
            break
        out.append((w, ps[0]))
        if ps[0].tag.POS in ("NOUN", "NPRO"):
            break
    if not out or out[-1][1].tag.POS not in ("NOUN", "NPRO"):
        return []
    return out


def _inflect_np(np, case):
    res = []
    for w, p in np:
        new = p.inflect({case})
        if new is None:
            return None
        res.append((w, _keep_case(w.group(0), new.word)))
    return res


def _between_is_space(text, a, b):
    return text[a.end():b.start()].strip() == ""


def _morph_edits(text):
    """Возвращает список правок (start, end, replacement) и названия правил."""
    words = list(WORD_RE.finditer(text))
    edits, names = [], []
    i = 0
    while i < len(words):
        w = words[i]
        low = w.group(0).lower()
        nxt = words[i + 1] if i + 1 < len(words) else None
        adjacent = nxt is not None and _between_is_space(text, w, nxt)

        # является/являются + творительный -> тире + именительный
        if low in ("является", "являются") and adjacent and nxt.group(0).lower() != "ли" and i > 0:
            np = _collect_np(words, i + 1, "ablt")
            inflected = _inflect_np(np, "nomn") if np else None
            if inflected:
                edits.append((w.start(), nxt.start(), "— "))
                edits += [(x.start(), x.end(), new) for x, new in inflected]
                names.append(f"{w.group(0)} → —")
                i += 1 + len(np)
                continue
        # является/являются одним из ... -> — один из ...
        if low in ("является", "являются") and adjacent and i > 0 and i + 2 < len(words) \
                and words[i + 2].group(0).lower() == "из" and MORPH is not None:
            p = next((x for x in _parses(nxt.group(0), "ablt") if "Anum" in x.tag or x.normal_form == "один"), None)
            new = p.inflect({"nomn"}) if p else None
            if new:
                edits.append((w.start(), nxt.start(), "— "))
                edits.append((nxt.start(), nxt.end(), new.word))
                names.append(f"{w.group(0)} {nxt.group(0)} из → — {new.word} из")
                i += 2
                continue
        # являлся/... -> был/... (творительный остаётся верным)
        if low in PAST_YAVL:
            edits.append((w.start(), w.end(), _keep_case(w.group(0), PAST_YAVL[low])))
            names.append(f"{w.group(0)} → {PAST_YAVL[low]}")
        # будет являться X -> будет X
        if low == "являться" and i > 0 and words[i - 1].group(0).lower().startswith("буд"):
            edits.append((words[i - 1].end(), w.end(), ""))
            names.append("будет являться → будет")
        # данный/данного... + согласованное слово -> этот/этого...
        if low in DANN_SING and adjacent and MORPH is not None:
            done = False
            for p in _parses(low):
                if p.normal_form != "данный" or p.tag.number != "sing":
                    continue
                for q in _parses(nxt.group(0)):
                    if q.tag.POS not in NP_POS or q.tag.case != p.tag.case or q.tag.number != "sing":
                        continue
                    if q.tag.gender and p.tag.gender and q.tag.gender != p.tag.gender:
                        continue
                    tags = {p.tag.case, "sing"}
                    if p.tag.gender:
                        tags.add(p.tag.gender)
                    if p.tag.case == "accs" and p.tag.gender == "masc" and q.tag.animacy:
                        tags.add(q.tag.animacy)
                    new = MORPH.parse("этот")[0].inflect(tags)
                    if new:
                        edits.append((w.start(), w.end(), _keep_case(w.group(0), new.word)))
                        names.append(f"{w.group(0)} → {new.word}")
                        done = True
                    break
                if done:
                    break
        # осуществлять -> проводить (в той же форме)
        if low.startswith("осуществ") and MORPH is not None:
            for p in _parses(low):
                if p.tag.POS not in ("VERB", "INFN") or not p.normal_form.startswith("осуществ"):
                    continue
                target = {"осуществлять": "проводить", "осуществить": "провести",
                          "осуществляться": "проводиться", "осуществиться": "провестись"}.get(p.normal_form)
                if not target:
                    break
                keep = {g for g in p.tag.grammemes
                        if g not in ("impf", "perf", "tran", "intr", "VERB", "INFN", "Refl")}
                base = MORPH.parse(target)[0]
                new = base.inflect(keep) if keep else base
                if new:
                    edits.append((w.start(), w.end(), _keep_case(w.group(0), new.word)))
                    names.append(f"{w.group(0)} → {new.word}")
                break
        i += 1

    # «в связи с» + творительный -> «из-за» + родительный
    for m in re.finditer(r"(?i)\bв связи с(?:о)?\s+", text):
        after = [x for x in words if x.start() >= m.end()]
        if not after or MORPH is None:
            continue
        np = _collect_np(after, 0, "ablt")
        inflected = _inflect_np(np, "gent") if np else None
        if inflected:
            edits.append((m.start(), m.end(), _keep_case(m.group(0), "из-за ")))
            edits += [(x.start(), x.end(), new) for x, new in inflected]
            names.append("в связи с → из-за")
    # «с целью» + инфинитив -> «чтобы», + существительное -> «для» (тот же родительный)
    for m in re.finditer(r"(?i)\s*\bс целью\s+", text):
        after = [x for x in words if x.start() >= m.end()]
        if not after or MORPH is None:
            continue
        p = MORPH.parse(after[0].group(0))[0]
        lead = m.group(0)[:len(m.group(0)) - len(m.group(0).lstrip())]
        prev = text[:m.start()].rstrip()[-1:]
        if p.tag.POS == "INFN":
            # перед «чтобы» внутри предложения нужна запятая
            repl = "чтобы " if (not prev or prev in ".!?\n,") else ", чтобы "
            lead = lead if repl.startswith("ч") else ""
        else:
            repl = "для "
        edits.append((m.start(), m.end(), lead + _keep_case(m.group(0).strip(), repl.lstrip(", ")) if repl[0] != "," else repl))
        names.append(f"с целью → {repl.strip()}")
    return edits, names


def _apply(text, edits):
    out, pos = [], 0
    for a, b, rep in sorted(edits, key=lambda e: e[0]):
        if a < pos:  # пересечение правок - пропускаем более позднюю
            continue
        out.append(text[pos:a])
        out.append(rep)
        pos = b
    out.append(text[pos:])
    return "".join(out)


def _drop_bait(text, hits):
    lines = []
    for line in text.split("\n"):
        sents = re.findall(r"[^.!?…]+(?:[.!?…]+|$)\s*", line) or [line]
        kept = [s for s in sents if not BAIT_RE.search(s)]
        if len(kept) != len(sents):
            hits.append({"rule": "дежурный призыв — предложение удалено",
                         "count": len(sents) - len(kept)})
            if not "".join(kept).strip():
                continue
        lines.append("".join(kept).rstrip() if len(kept) != len(sents) else line)
    return "\n".join(lines)


def fix(text):
    """Возвращает (исправленный текст, список правок)."""
    hits = []
    text = _drop_bait(text, hits)
    for pattern, repl in SAFE:
        n = len(pattern.findall(text))
        if n:
            text = pattern.sub(lambda m, r=repl: _keep_case(m.group(0), r(m)), text)
            hits.append({"rule": pattern.pattern.replace("(?i)", "").replace("\\b", ""), "count": n})
    edits, names = _morph_edits(text)
    if edits:
        text = _apply(text, edits)
        for n in sorted(set(names)):
            hits.append({"rule": n, "count": names.count(n)})
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text, hits


if __name__ == "__main__":
    raw = sys.stdin.read() if len(sys.argv) < 2 or sys.argv[1] == "-" else open(sys.argv[1], encoding="utf-8").read()
    fixed, report = fix(raw)
    sys.stdout.write(fixed)
    for h in report:
        print(f"  {h['count']}x  {h['rule']}", file=sys.stderr)
