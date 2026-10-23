"""Zerlegt Text in Abschnitte mit Überlappung."""

from typing import List, Tuple


Abschnitt = Tuple[int, str]  # (stelle, text)


def zerlegen(text: str, groesse: int = 500, ueberlappung: int = 75) -> List[Abschnitt]:
    """Zerlegt Text in Abschnitte zur Einbettung.
    
    - groesse: maximale Zeichen pro Abschnitt
    - ueberlappung: Zeichen, die vom Ende eines Abschnitts am Anfang des nächsten stehen
    """
    if not text:
        return []
    
    # Ersten Absatz/Text finden
    paragraphs = _split_paragraphs(text)
    if not paragraphs:
        return [(0, text)] if len(text) <= groesse else _zerlege_text(text, 0, groesse, ueberlappung)
    
    result: List[Abschnitt] = []
    current_stelle = 0
    
    for para in paragraphs:
        para_start = text.find(para, current_stelle)
        para_stelle = para_start if para_start != -1 else current_stelle
        
        if len(para) <= groesse:
            result.append((para_stelle, para))
        else:
            chunked = _zerlege_text(para, para_stelle, groesse, ueberlappung)
            result.extend(chunked)
        
        current_stelle = para_start + len(para)
    
    result = _bereinige_rests(result)
    
    return result


def _split_paragraphs(text: str) -> List[str]:
    """Trennt Text nach Paragraphen (Doppelzeilenumbruch)."""
    parts = text.split('\n\n')
    return [p for p in parts if p]


def _zerlege_text(text: str, start_stelle: int, groesse: int, ueberlappung: int) -> List[Abschnitt]:
    """Zerlegt Text in Abschnitte, nie mittendurch Wort."""
    result: List[Abschnitt] = []
    
    while text:
        if len(text) <= groesse:
            result.append((start_stelle, text))
            break
        
        cut_pos = _finde_schnittstelle(text, groesse)
        
        if cut_pos == 0:
            result.append((start_stelle, text))
            break
        
        chunk = text[:cut_pos]
        result.append((start_stelle, chunk))
        
        # Überlappung von Ende des aktuellen Chunks
        overlap_start = max(0, cut_pos - ueberlappung)
        overlap = text[overlap_start:cut_pos]
        text = text[cut_pos:]
        start_stelle = cut_pos
    
    return result


def _finde_schnittstelle(text: str, groesse: int) -> int:
    """Finde beste Schnittstelle vor groesse, nie im Wort."""
    # Suche nach Absatzgrenze
    for sep in ['\n\n', '\n']:
        pos = text.rfind(sep, 0, groesse)
        if pos > 0:
            return pos
    
    # Suche nach Satzgrenze
    for sep in ['. ', '! ', '? ']:
        pos = text.rfind(sep, 0, groesse)
        if pos > 0:
            return pos + len(sep)
    
    # Suche nach Wortgrenze
    pos = text.rfind(' ', 0, groesse)
    if pos > 0:
        return pos + 1
    
    # Suche nach jedes Zeichen
    return groesse


def _bereinige_rests(result: List[Abschnitt]) -> List[Abschnitt]:
    """Hängt kurze Reste (<20 Zeichen) an vorangehenden Abschnitt."""
    if len(result) <= 1:
        return result
    
    new_result: List[Abschnitt] = []
    i = 0
    
    while i < len(result):
        s, t = result[i]
        
        if len(t) < 20 and i > 0:
            old_stelle, old_text = new_result.pop()
            new_result.append((old_stelle, old_text + ' ' + t))
        else:
            new_result.append((s, t))
        
        i += 1
    
    return new_result
