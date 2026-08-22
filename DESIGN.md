# Design

Visuelle Welt: **die Designsprache von Windows 11 (Fluent), voll ausgeführt.**
Gewählt als stehende Alternative — Konvention ist hier die Verpflichtung, nicht der
Kompromiss. Qualitätslatte: Windows Terminal und Windows-Einstellungen. Kein Zitat,
keine Ironie, keine eingeschmuggelte Eigenheit. Wer die App neben den Einstellungen
öffnet, soll keinen Bruch bemerken.

Modus: **Operate.** Die Person ist in einer Aufgabe. Vertrautheit ist hier ein
Merkmal, kein Mangel; das Werkzeug soll in der Aufgabe verschwinden.

## Plattformgrenze (bindend)

Tkinter kennt keine Deckkraft auf Widgets, keine Schatten, keine Transitions, kein
Mica und keine Easing-Kurven. Daraus folgt für dieses System:

- Fluents Alpha-Ebenen (`#FFFFFF0A` auf Grund) werden als **volltonige
  Ersatzfarben** ausgerechnet und fest hinterlegt.
- Runde Ecken (Fluent: 4 px, bei Flächen 8 px) entstehen **auf einem Canvas
  gezeichnet**, nicht als Widget-Eigenschaft. Steuerelemente sind deshalb selbst
  gezeichnet, nicht `tk.Button`.
- Bewegung entfällt bis auf Zustandswechsel, die ohnehin sofort sind. Kein
  Nachbauen von Übergängen über getaktete `after()`-Schleifen.
- Mica-Transparenz wird **nicht** imitiert. Stattdessen die Ebenenlogik von Fluent
  über solide Flächenwerte.

## Farbe

Strategie: **Restrained** — Neutrale plus ein Akzent. Der Akzent trägt
ausschließlich die primäre Aktion, die aktuelle Auswahl und Zustandsanzeigen. Nie
Dekoration, nie große Flächen.

| Rolle | Wert | Verwendung |
| --- | --- | --- |
| `BG_BASE` | `#202020` | Fensterhintergrund, Navigationsspalte |
| `BG_LAYER` | `#272727` | Inhaltsfläche |
| `BG_CARD` | `#2B2B2B` | Karten, Listenzeilen, Eingabefelder in Ruhe |
| `BG_CARD_HOVER` | `#323232` | Karte/Zeile unter dem Zeiger |
| `BG_INPUT_FOCUS` | `#1F1F1F` | Eingabefeld mit Schreibmarke |
| `STROKE` | `#353535` | Trennlinien, Kartenrand |
| `STROKE_STRONG` | `#454545` | Rand eines Steuerelements |
| `TEXT` | `#FFFFFF` | Primärtext |
| `TEXT_SECONDARY` | `#C5C5C5` | Beschriftungen, Sekundärtext |
| `TEXT_TERTIARY` | `#8A8A8A` | Hinweise, deaktiviert |
| `ACCENT` | `#60CDFF` | Primärfläche, Auswahl, Fokus |
| `ACCENT_HOVER` | `#7ED8FF` | Primärfläche unter dem Zeiger |
| `ACCENT_PRESS` | `#42B8F0` | Primärfläche gedrückt |
| `ON_ACCENT` | `#003A5C` | Text auf Akzentfläche |
| `SUCCESS` | `#6CCB5F` | Zustand: abgerufen/erfolgreich |
| `CAUTION` | `#FCE100` | Zustand: wartet, Aufmerksamkeit |
| `DANGER` | `#FF99A4` | Zustand: verbrannt, Fehler |

Zustand wird **nie allein über Farbe** transportiert: neben jedem Farbzeichen steht
das Wort.

## Typografie

Eine Familie: **Segoe UI Variable Text**, Rückfall auf **Segoe UI**. Maschinenwerte
— Schlüssel, Kennungen, Uhrzeiten, Zähler — in **Cascadia Mono**, Rückfall
**Consolas**. Monospace nur für Daten, nie als Kostüm.

Fluent-Rampe, feste Größen (kein fließendes Skalieren):

| Rolle | Größe / Gewicht |
| --- | --- |
| Title | 28 px, Semibold — Bereichsüberschrift, einmal je Ansicht |
| Subtitle | 20 px, Semibold — Gruppen in den Einstellungen |
| Body Strong | 14 px, Semibold — Kartentitel, Knöpfe |
| Body | 14 px, Regular — Fließtext, Eingaben |
| Caption | 12 px, Regular — Beschriftungen, Meta, Hilfetext |

**Kein Kicker über einer Überschrift.** Die bisherigen Augenbrauen („NEUES SECRET"
über „Einmal-Link erstellen") entfallen ersatzlos; die Überschrift trägt sich selbst.

## Raster und Abstände

4-px-Grundeinheit, verwendete Stufen: 4, 8, 12, 16, 20, 24, 32, 40.
Über einer Überschrift steht mehr Luft als darunter. Inhaltsbreite höchstens 640 px
für Formulare, Listen laufen auf volle Breite.

## Komponenten

Jedes interaktive Element führt **alle** Zustände: Ruhe, Zeiger, Fokus (sichtbarer
Ring), gedrückt, deaktiviert, arbeitend. Ein Element, das die Hälfte davon
mitbringt, ist unfertig.

- **Button** (Canvas, r=4): `accent` (primär, eine je Ansicht), `standard`
  (Umriss), `subtle` (nur Text). Gedrückt wird die Fläche dunkler — kein Skalieren,
  das Tk nicht sauber kann.
- **TextField / TextArea** (Canvas-Rahmen, r=4): unter der Schreibmarke bekommt der
  untere Rand die Akzentfarbe — Fluents Kennzeichen für ein aktives Feld.
- **SegmentedControl** für die Gültigkeit: eine zusammenhängende Leiste, die
  gewählte Kachel trägt die Akzentfläche.
- **NavigationView** links: 48 px hohe Einträge, gewählter Eintrag mit
  Akzentbalken links und eigener Fläche.
- **ListRow** für den Verlauf: eine Karte je Eintrag, Zustandszeichen und Wort
  links, Zeitangabe und Meta darunter, Aktionen rechts — Aktionen dürfen den Text
  nie beschneiden.
- **InfoBar** statt schwebender Sprechblase: eine Leiste am unteren Rand des
  Inhalts, mit Zustandsfarbe am linken Rand (1 px), Text und Schließen.
- **Scrollbar**: schmal, ohne Pfeile, Daumen in `#4A4A4A`, unter dem Zeiger heller.

Ikonografie: gezeichnet auf Canvas, eine Strichstärke (1,3 px), Fluent-Geometrie.
**Keine Unicode-Zeichen als Ersatz für Symbole** — das bisherige „●" und „×"
entfallen.

## Zustände und Leere

- Leerer Verlauf erklärt den nächsten Schritt, statt „nichts vorhanden" zu melden.
- Fehlende Zugangsdaten sind kein Fehler, sondern ein Erstlauf: die Sendeansicht
  führt in die Einstellungen.
- Ladezustände zeigen den betroffenen Knopf als arbeitend, nicht die ganze Ansicht.

## Was dieses System nicht tut

- Keine gleich großen Karten aus Symbol + Überschrift + Text als Seitenstruktur.
- Keine Farbverläufe, kein Glas, keine Schlagschatten-Imitate.
- Keine Akzentfarbe auf ruhenden Elementen.
- Kein Modal für etwas, das inline entschieden werden kann. Die einzige Ausnahme
  bleibt die Rückfrage vor dem Verbrennen — sie schützt vor einer nicht
  umkehrbaren Handlung.
