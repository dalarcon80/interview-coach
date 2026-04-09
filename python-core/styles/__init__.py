"""
Interview Coach - Response Styles
4 response styles: Executive, Commercial, Technical, Mixed

Per ARCHITECTURE.md Section 11:
- Executive: Acción → Método → Resultado con métricas (150-220 palabras)
- Commercial: Necesidad empresa → Tu prueba → Valor futuro
- Technical: Problema → Analysis/Trade-offs → Implementación → Outcome
- Mixed: Auto-detecta según QuestionType
"""
from .registry import (
    BaseStyle,
    ExecutiveStyle,
    CommercialStyle,
    TechnicalStyle,
    MixedStyle,
    StyleRegistry,
    get_style_for_type,
)

__all__ = [
    "BaseStyle",
    "ExecutiveStyle",
    "CommercialStyle",
    "TechnicalStyle",
    "MixedStyle",
    "StyleRegistry",
    "get_style_for_type",
]
