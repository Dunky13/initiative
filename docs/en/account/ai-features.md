---
icon: lucide/sparkles
---

# AI features

Initiative has optional AI help for the boring parts — drafting a task description, breaking a task into a checklist, summarising a file.

Optional, off unless somebody deliberately switches it on, and never quietly running in the background while you weren't looking.

## What it can do

When AI is switched on, you'll see **Generate** options in a few places:

- Drafting or improving a **task description**.
- Suggesting a **checklist** to break something down.
- Producing a **summary** of a file.

You ask each time. Nothing writes itself while you're making tea.

## Who sets it up

Whoever runs the server decides who's in charge of AI, under **Settings → Platform → Integrations**. One of three, for the whole server:

| Mode | What it means |
|---|---|
| **Disabled** | AI is off for everyone. |
| **Platform-managed** | The server's owner sets up the AI every community uses. |
| **Community-managed** | Each community's [superadmin](../guides/communities.md#why-superadmin-is-separate) sets up its own, under **Community settings → Integrations**. |

Never both. What they set up are **connections**: a provider, a model and a key.

| Provider | Notes |
|---|---|
| **OpenAI**, **Anthropic**, **Google Gemini**, **DeepSeek**, **Groq**, **xAI**, **Together AI**, **OpenRouter** | Hosted services. Each needs an API key from that company. |
| **OpenAI-compatible server** | Anything that speaks the OpenAI API, at the address the connection gives: vLLM, llama.cpp, LM Studio, LocalAI, or a gateway your company already runs. The key is optional. |
| **Ollama** | Models on a machine of the server owner's. Only they can set one up. |

The model comes from the provider's own list, so save the connection once and pick from what it offers. A connection without a model sits there doing nothing until somebody picks one, which is at least restful.

Only the server's owner can point a connection at a machine on a private network, and only for Ollama or an OpenAI-compatible server.

With more than one connection, everybody uses the one marked as the default.

## Your part

Nothing. There's no key to find, no form to fill in and no setting to get wrong. If the **Generate** buttons are there, somebody has already done the setting up, and the bill is theirs too.

## The privacy bit, which is genuinely worth reading

AI features work by sending the relevant text — a task's details, a file's contents — to whichever provider is configured. That content **leaves your server** and goes to that company, under *their* terms.

This is the one place in Initiative where your work deliberately goes somewhere else, so we'd rather be precise about it than reassuring:

- **We never train on your content, and there's no path for us to.** That's a fact about the architecture, not a promise about our behaviour. See [Why the rules are what they are](../security/data-and-compliance.md#why-the-rules-are-what-they-are).
- **What the provider does with it is between you and them.** The moment you press Generate, that text is governed by whatever you agreed to with OpenAI, Anthropic, or whoever else. Some providers train on what they receive; some don't; some let you choose. We can't promise on their behalf, and we won't pretend to.

Which is precisely why the buttons are explicit, why nothing generates on its own, and why the whole thing can be switched off.

!!! tip "Want a hard guarantee? Keep it local."
    Whoever runs your server can configure a **local** provider: Ollama, or an OpenAI-compatible server such as vLLM on their own machine. The text never leaves your server, so there's no third party's terms to read and nothing to take anyone's word for. If your group's work is the kind you wouldn't hand a stranger, this is the option to ask for.

Not sure what's configured on your server? Ask a community admin or whoever runs the server — or simply never press the buttons. Everything else in Initiative works exactly the same without them, and nobody is keeping score.

## Related

- [Profile & preferences](profile-and-preferences.md) — your other personal settings.
- [Platform configuration](../running-a-server/configuration.md) — for whoever runs the server.
