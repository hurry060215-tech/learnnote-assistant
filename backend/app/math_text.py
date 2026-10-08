"""Local readable math projection; original expressions remain in semantic blocks.

Common grouped TeX notation is rendered as unambiguous linear math. Unknown
commands remain verbatim. No commands are executed and no files are read.
"""
from __future__ import annotations
import re
_COMMANDS = {'partial':'∂','alpha':'α','beta':'β','gamma':'γ','delta':'δ','theta':'θ','lambda':'λ','mu':'μ','pi':'π','sigma':'σ','tau':'τ','phi':'φ','omega':'ω','Delta':'Δ','Sigma':'Σ','Omega':'Ω','sum':'Σ','int':'integral','infty':'infinity','cdot':'·','times':'×','div':'÷','pm':'±','leq':'≤','geq':'≥','neq':'≠','le':'≤','ge':'≥','rightarrow':'→','leftarrow':'←','approx':'≈','equiv':'≡','quad':' ','qquad':'  ','left':'','right':''}
_INLINE = re.compile(r'(?<!\\)\$(?!\$)([^$\n]+)\$(?!\$)')

def render_math_text(expression: str) -> str:
    text = str(expression or '').strip()
    for _ in range(32):
        previous = text
        text = re.sub(r'([_^])\{([^{}]*)\}',lambda m:m[1]+'('+m[2]+')',text)
        text = re.sub(r'\\(?:dfrac|tfrac|frac)\s*\{([^{}]*)\}\s*\{([^{}]*)\}',lambda m:f'({m[1]})/({m[2]})',text)
        text = re.sub(r'\\sqrt\s*\{([^{}]*)\}',lambda m:f'sqrt({m[1]})',text)
        text = re.sub(r'\\(?:text|mathrm|mathbf|mathit)\s*\{([^{}]*)\}',lambda m:m[1],text)
        if text == previous: break
    text = re.sub(r'\\([A-Za-z]+)',lambda m:_COMMANDS.get(m[1],m[0]),text)
    text = re.sub(r'([_^])\{([^{}]*)\}',lambda m:m[1]+'('+m[2]+')',text)
    return re.sub(r'\\[,;!]',' ',text)

def math_source_requires_fallback(expression: str) -> bool:
    return bool(re.search(r'\\[A-Za-z]+',render_math_text(expression)))

def inline_math_expressions(text: str) -> list[str]:
    return [m[1] for m in _INLINE.finditer(str(text or ''))]
