# user-stories

User story tools for a Product Owner. Nothing here needs Obsidian: it works in any
Claude Code session, and in Claude with the same skill uploaded.

## us-craft

Give Claude a rough draft or a one-line ticket and get back a finished story in the
Antoine template. Say "craft MYLE-123", "make this a proper story" with a draft
pasted, or "mets cette US au propre" with the note open.

### What it does

1. **Reads the draft:** a Jira key or URL, a file, the open note, or pasted text.
2. **Reads the context:** the parent epic, related stories in the project, linked
   issues, the Confluence page that documents the feature, and the Figma frame when
   there is a link. It uses the names the team already uses for screens and buttons.
3. **Asks you** the few questions the draft and the context leave open (a behavior
   nobody decided, an offline case, a missing Figma link), at most 4, with
   clickable answers. When the story would have more than 8 scenarios, it also
   proposes a split.
4. **Writes the story** to the standard in `skills/us-craft/guide.md`:
   - the real role, one goal and a real benefit,
   - short scenarios about behavior only: success from each entry point, errors,
     the product's states (offline, in progress), cancel and close, and who is
     refused when patient data or roles are involved,
   - "I navigate to" for a screen change, "I see" for new information on the screen,
   - Out of scope (what other stories cover), Mocks, a Vocab Table holding every UI
     text in EN, FR and ES, and related references.
5. **Shows you the result:** the story, then a short "For you, not for the ticket"
   list (assumptions, suggested translations, empty cells). Questions never go in the
   ticket.

### Your answers decide what happens

| Claude asks | Yes | No |
|---|---|---|
| The questions before writing | Your answers become scenarios | "Just write it": best guesses, listed for you after the story |
| A split | It writes every story, each naming the others in Out of scope | One story, with all its scenarios |
| "Put it in MYLE-123's description?" | The description is replaced (Jira keeps the old one in its history). Nothing else on the ticket changes | Jira is untouched. Copy the story yourself |
| "...and create the other stories, linked to it?" (after a split) | New stories in the same project and parent, all linked "relates to", keys added to each Out of scope | Nothing is created |
| "Put it in the note?" | Only that draft in the note is replaced | The note is untouched |

Reading Jira, Confluence and Figma never changes anything.

Needs the Atlassian connector for Jira and Confluence, and the Figma connector to
read mocks. Without them, paste the draft.

## Install

```
/plugin install user-stories@po-claude-toolkit
```

To use the skill in Claude (web or desktop) without Claude Code, zip the
`skills/us-craft` folder (it holds both `SKILL.md` and `guide.md`) and upload it
under Settings > Capabilities > Skills.
