from pathlib import Path

p=Path(r"C:\New Projet\MEMORIA-PERMANENTE\src\memory_permanent\input_guard.py")
s=p.read_text(encoding="utf-8-sig")
old='''        if re.search(r"\\b(mark|treat|consider|set|declare|classify|marque|trate|considere|defina|declare)\\b.{0,80}\\b(trusted|validated|authoritative|governor.?eligible|confiavel|validado|autoritativo)\\b", text):
            signals.append(("SELF_ATTEST_TRUST", 45))
        return signals
'''
new='''        if re.search(r"\\b(mark|treat|consider|set|declare|classify|marque|trate|considere|defina|declare)\\b.{0,80}\\b(trusted|validated|authoritative|governor.?eligible|confiavel|validado|autoritativo)\\b", text):
            signals.append(("SELF_ATTEST_TRUST", 45))
        names = {name for name, _ in signals}
        if "OVERRIDE_CONTROL" in names:
            signals.append(("CONTROL_OVERRIDE", 0))
        if "DISABLE_SECURITY" in names:
            signals.append(("SECURITY_BYPASS", 0))
        return signals
'''
if old not in s:
    raise SystemExit('semantic block not found')
s=s.replace(old,new,1)
old2='''            if kind != "RAW":
                reasons.extend(["ENCODED_INSTRUCTION_PAYLOAD", f"ENCODED_PAYLOAD:{kind}"])
                best = max(best, min(100, score + 15))
'''
new2='''            if kind != "RAW":
                reasons.extend(["ENCODED_INSTRUCTION_PAYLOAD", f"ENCODED_PAYLOAD:{kind}"])
                if kind == "PERCENT":
                    reasons.append("ENCODED_PAYLOAD:URL_PERCENT")
                best = max(best, min(100, score + 15))
'''
if old2 not in s:
    raise SystemExit('encoding block not found')
s=s.replace(old2,new2,1)
p.write_text(s,encoding='utf-8',newline='\n')
print('patched')
