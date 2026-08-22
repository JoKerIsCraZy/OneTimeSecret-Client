# Product

<!-- impeccable:product-schema 1 -->

## Platform

desktop

<!-- Kein Wert des Schemas (web/ios/android/adaptive) trifft zu: Windows-Desktop,
     Python 3.12 mit Tkinter/ttk, ausgeliefert als PyInstaller-Single-File-.exe. -->

## Stack

Bestehende Codebasis: Python 3.12, Tkinter/ttk, `requests`, `keyring`. Eine Datei
(`OneTimeSecret_Client.py`), Build via PyInstaller `--onefile --windowed`.

## Users

Primär eine IT-/Admin-Person, die gelegentlich — ein paar Mal pro Woche, zwischen
anderen Aufgaben — Zugangsdaten, Lizenzschlüssel oder Passwörter an Kollegen und
Kunden weitergibt. Kein Dauerbetrieb, kein Ticket-Takt: die App wird geöffnet,
benutzt und wieder geschlossen. Sie muss sich nach Wochen Pause ohne Einarbeitung
wieder erschließen.

## Product Purpose

Einen Einmal-Link erzeugen und weitergeben, ohne den Browser zu öffnen und ohne
eine Konfigurationsdatei anzufassen. Danach nachvollziehen, ob der Empfänger ihn
abgerufen hat, und ihn notfalls vorher vernichten. Erfolg heißt: Link in der
Zwischenablage, in unter zehn Sekunden, ohne dass jemand über Einstellungen
nachdenken muss.

## Positioning

Ein nativer Desktop-Client für die OneTimeSecret-v2-API statt der Weboberfläche.
Der Unterschied, den eine Webseite nicht bieten kann: der API-Key liegt im Windows
Credential Manager (DPAPI, pro Benutzer) statt in einem Browser-Profil, und der
Zustand eines Secrets wird über die API geprüft — nie durch Öffnen des
Empfänger-Links, was ihn verbrauchen würde.

## Operating Context

- Windows 10/11, meist an einem Arbeitsplatzrechner, im Wechsel mit anderen Fenstern.
- Auslieferung als einzelne `.exe`; auf dem Zielrechner ist kein Python nötig.
- Zustand auf der Platte: `%APPDATA%\OneTimeSecret\settings.json` und `history.json`.
- Regionen: EU (Vorgabe), Global, US, UK, CA, NZ oder eigener Host.
- Zwei Sprachen, zur Laufzeit umschaltbar: Englisch (Vorgabe) und Deutsch.

## Capabilities and Constraints

**Kann:** Secret verbergen (`conceal`) mit TTL-Vorgaben von 5 Minuten bis 14 Tagen,
optionalem Empfänger und optionaler Passphrase; Zustand abfragen; vor dem Abruf
verbrennen; Empfänger-Link nachträglich vom Server holen; Verbindung und
Zugangsdaten testen; Verlauf von bis zu 200 Einträgen.

**Muss bleiben (vom Nutzer bestätigt):** eine Datei plus PyInstaller-Build, keine
neuen Abhängigkeiten; Deutsch und Englisch vollständig; dunkles Erscheinungsbild.

**Plattformgrenze:** Tkinter kennt keine Deckkraft auf Widgets, keine runden Ecken,
keine Schatten, keine Transitions und keine Easing-Kurven. Bewegung entsteht nur
über getaktete `after()`-Aufrufe und ist entsprechend teuer. Gestaltung findet über
Farbe, Typografie, Raster, Dichte, 1px-Linien und Canvas-Zeichnung statt.

**Nicht entschieden:** heller Modus (kein Ziel), weitere Sprachen, Mehrbenutzerbetrieb.

## Brand Commitments

- Name: **OneTimeSecret Client**. Nicht mit OneTimeSecret selbst verbunden.
- Icon: `assets/onetime.ico` — Rautenmarke auf dunklem Grund, reproduzierbar über
  `assets/generate_icon.py`.
- Dunkles Erscheinungsbild ist gesetzt.
- **Designsprache: die von Windows selbst (Fluent).** Vom Nutzer als stehende
  Entscheidung gewählt; Qualitätsmaßstab sind Windows Terminal und die
  Windows-Einstellungen. Die App fügt sich in die Plattform ein, statt eine eigene
  Bildsprache mitzubringen.

## Evidence on Hand

- Die echte API und ihr Spec: `https://api.onetimesecret.com/doc/api-v2.json`.
- Verifiziertes Serververhalten aus dieser Arbeit: Burn braucht `continue`; eine
  Ablehnung kommt als HTTP 200 mit `success: false`; `/private/<id>` ist v1 und
  antwortet mit 404, `/receipt/<id>` ist der gültige Pfad.
- Keine Nutzerzahlen, keine Referenzkunden, keine Benchmarks. Nichts davon erfinden.

## Product Principles

1. **Senden ist der Hauptweg.** Der Weg von „App offen" zu „Link in der
   Zwischenablage" ist der einzige, der jedes Mal begangen wird. Alles andere ordnet
   sich ihm unter.
2. **Der Empfänger-Link ist das Geheimnis.** Er wird nie auf der Platte gespeichert;
   wird er später gebraucht, holt ihn der Client vom Server.
3. **Zustand kommt vom Server.** Nie durch Öffnen des Empfänger-Links — das würde ihn
   verbrauchen.
4. **Keine Sicherheitszusage ohne Deckung.** Die Oberfläche sagt, wo der Key
   tatsächlich gelandet ist, statt zu behaupten, was vorgesehen war.
5. **Jede Meldung in der eingestellten Sprache** — auch die vom Server ausgelösten.

## Accessibility & Inclusion

Vollständig mit der Tastatur bedienbar (Senden, Abbrechen, Bereichswechsel). Text
und Zustandsfarben müssen auf dunklem Grund lesbar bleiben; Zustand wird nie allein
über Farbe transportiert, sondern immer zusätzlich als Wort.
