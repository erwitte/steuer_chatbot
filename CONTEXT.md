# Steuer Chatbot

A personal Telegram bot that captures evidence and metadata for a single user's German income-tax deductions, organized into a fixed set of deduction categories.

## Language

**Entry**:
A single logged claim against one Category, belonging to exactly one Tax Year, derived from the date the user provides.
_Avoid_: record, claim, item.

**Category**:
One of four fixed deduction types the bot tracks: Homeoffice-Pauschale, Pendlerpauschale, Weiterbildung, Arbeitsmittel. The set is closed for v1 — not a user-managed list.
_Avoid_: type, kind.

**Tax Year**:
The German calendar-year tax period an Entry belongs to, derived automatically from the Entry's date rather than chosen explicitly by the user.

**Receipt**:
The photo or PDF attached to an Entry as evidence of a cost. Required for Weiterbildung and Arbeitsmittel entries; not applicable to Homeoffice-Pauschale or Pendlerpauschale, which are flat-rate and have no associated cost document.

**Commute Distance**:
The user's fixed, round-trip daily commute distance, set once and reused for every Pendlerpauschale Entry rather than re-entered each time.

### Categories

**Homeoffice-Pauschale**:
Flat-rate deduction for days worked from home. An Entry records a date or day-count; no Receipt.

**Pendlerpauschale**:
Flat-rate deduction for days commuting to the office, calculated against the Commute Distance. An Entry records a date or day-count; no Receipt.

**Weiterbildung**:
Deductible professional training expense. An Entry records one total cost for a course or training trip (covering course fee, travel, hotel, and meals together, not itemized) plus a Receipt.

**Arbeitsmittel**:
Deductible work-equipment purchase for home-office use. An Entry records a cost and a Receipt.
