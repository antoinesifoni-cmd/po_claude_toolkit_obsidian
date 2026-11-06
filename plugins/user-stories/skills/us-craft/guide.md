# User story writing guide (the "Antoine template")

How a finished story looks. The `us-craft` skill writes every story to this standard.

## What goes where

Each section has one job. Don't repeat a detail in two places.

- **Scenarios:** behavior only. What I do and what happens. No UI text, no sample
  data, no design detail.
- **Vocab Table:** every UI text: titles, messages, button labels, in each language.
  A scenario points to it by its token.
- **Mocks:** the look. Layout, colors, icons, placement.
- **Technical Details:** filled by the team later.
- **Questions and assumptions never go in the ticket.** They are settled with the PO
  before writing, or reported to the PO next to the story. No Open questions section,
  no Assumptions label, no `[to confirm]` markers.

## Template

Sections in this order. Remove an optional section when it has nothing in it.

```
# [Short title describing the behavior]

*This is a draft made by Claude using the Antoine template. Please remove this sentence once you have revised your US.*

## Description
**As a** [role],
**I want to** [goal],
**so that** [benefit].

----

## Scenarios

### Background                      (optional)
**Given** [shared precondition]
**And** [shared precondition]

### Scenario 1: [Title]
**Given** I am on the [screen]
**And** [precondition]
**When** I [action]
**Then** [observable outcome]
**And** [observable outcome]

----

## Out of scope                     (optional)
- [item]

----

## Mocks
[Figma link or images. Placeholder when none:]
[Insert images here. A Figma link is preferred over static images, as it gives the team the full design context.]

----

## Vocab Table                      (optional)

| Token | EN | FR | ES |
|---|---|---|---|
| [token] | [English text] | [Quebec French text] | [Spanish text] |

----

## Technical Details
To be filled in later.

----

## AI Potential References          (optional)
*This is a reference list built by Claude and might not be fully related to this ticket. Use your judgment before following up on any of these.*

- [KEY-123 — Title](url): [why it is related]
```

Formatting:
- `----` between primary sections.
- Step keywords in bold: **Given**, **When**, **Then**, **And**, **But**. One step per
  line, no bullets.
- No emojis.

## Mocks

- Every Figma link that shows this story's screens, one per line, each with a short
  label naming what it shows: `[Delete confirmation pop-up (iOS and Android)](url)`.
- Links exactly as found, never rebuilt or made up. A link to a whole file only when
  there is none to a frame.
- No Figma link and no image: keep the placeholder.

## Description

- **Role:** the real one, using the product's own word for it (clinician,
  professional, nurse, medical secretary, clinic administrator, patient). "User" only
  when every role is concerned.
- **I want to:** one goal of that role, not a UI step. A draft with two goals becomes
  two stories: write the one the ticket's summary is about, and tell the PO about the
  other. The permission scenario of that other goal goes with it, not here.
- **So that:** a real benefit, never the action said again.
- **Title:** short, the behavior, not the screen ("Clinician deletes a consultation",
  not "Delete button").

## Scenarios

- First person singular, active voice, precise software terms: "I tap "Delete"",
  never "the button is tapped by the user".
- **Navigate or see.** "I navigate to the [screen]" when I end up on another screen
  ("**Then** I navigate to the Past consultations list"). "I see" only for new
  information appearing on the screen I am on: a pop-up, a message, a value, an item.
- One behavior per scenario, 6 steps at most, exactly one **When**. An **And** right
  after the When that is another action of mine is a second When: move the setup into
  Given steps, or split the scenario.
- When the system acts on its own (a reminder, a timeout, a nightly job), the When is
  the event: "**When** 24 hours remain before my appointment". The Thens stay what I
  see or receive.
- Every **Then** is something a tester can see: a screen, a pop-up, a state, a list
  entry, an item gone. Never "works correctly", "properly", "quickly",
  "user-friendly".
- **Generic, not sample data.** "a consultation", "a patient", "the consultation is
  not in the list". Never invented titles, names or values, unless the value itself is
  what the scenario tests (a limit, a format, a boundary).
- **UI text by token.** A message or label is named by its Vocab Table token, not
  quoted in full: "**Then** I see the delete confirmation pop-up", with the title,
  message and buttons in the Vocab Table. Short button names that are the action
  itself ("Delete", "Cancel") can stay in the step when they match a token.
- Background only when two or more scenarios share identical preconditions. No When or
  Then in it.
- No implementation detail (tables, endpoints, flags) unless the story is technical.
- Prefer many small scenarios to a few long ones.

Cover, in this order:
1. The main success path, from each entry point the story names.
2. At least one error or failure case.
3. When the story touches patient data or a role: someone without the right is refused.
4. The states the product really has that change the behavior (offline, not yet
   synced, in progress, empty). Context and the PO tell you which ones exist.
5. Cancel and close, when there is a confirmation.

## Size and splitting

More than 8 scenarios, or scenarios that fall into clearly separate groups, means the
story should be split. Split by what a developer could ship on its own:

- the main flow first (entry points, confirmation, success, failure),
- then each state or variant that adds its own work (offline, not yet synced, during a
  recording, a second role).

Each part is a complete story in this template, with its own Description, and must
make sense alone. Stories from one split stay connected:

- same parent epic,
- each one's Out of scope names the others ("Deleting while offline: MCA-1530"),
- linked in Jira with "relates to" once they exist.

## Medfar checks

Only when the story touches the area. Each becomes a scenario, a Vocab Table entry or
a question to the PO before writing.

- **Bilingual UI:** every new text has EN and Quebec French in the Vocab Table. Quebec
  terms: courriel (not email), rendez-vous, numéro d'assurance maladie (NAM).
- **Patient privacy (Quebec Law 25):** who can see or change the data, and whether the
  change is in the audit trail.
- **Clinical safety:** the right patient is identified, no silent data loss, no
  duplicate record or prescription.
- **Dates and times:** format and time zone (America/Toronto) where it matters.
- **Accessibility:** keyboard use and screen reader labels for new controls.

## Clarity

- No vague words: quickly, easily, properly, correctly, user-friendly, appropriate,
  some, etc., TBD, and/or.
- Vocab Table tokens are short and readable ("Delete confirmation title"), one row per
  text. Only texts this story adds or changes. Take the English from Figma when there
  is a frame. When a text exists in one language only, propose the others (Quebec
  French, neutral Spanish) and tell the PO they are proposals. A text nobody has
  decided yet keeps its row with the cells empty, and the PO is told.
- Never invent a business rule (a limit, a delay, who has which right, where I land
  after an action). Ask the PO before writing. If they don't know, write the most
  likely behavior and tell them it is an assumption.
