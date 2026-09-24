# Keeping this example simple

This repository is a teaching example. Its goal is that a newcomer learns how
the AAC system works by running it and reading it: which pieces there are,
and what each one hands to the next when an agent does one piece of
authorized work. It is not a model of engineering or security practice for
production systems. It is written in the spirit of
the quickstart samples of identity providers and the first-app tutorials of
web frameworks (Auth0's quickstarts, React's tic-tac-toe tutorial, Angular's
first app): small enough to read in one sitting, runnable in a few steps, and
honest about what it leaves out.

Everyone who changes it, people and coding agents alike, keeps to what
follows.

## What the example is for

* Show the moving parts and how they interact: the `aac` command-line tool
  (registers the tenant and generates every key, certificate and
  configuration file), the AAC sidecar beside the agent, the agent that makes
  the business decision, the publisher that makes the tenant's public keys
  available, and the hosted AAC service.
* Expose the inner workings in the simplest way. The example client prints
  each hand-off from what the components actually returned and recorded: the
  authority the sidecar minted, the decision the agent returned, what the
  sidecar verified and signed. It never prints a summary of its own making.
* Get a developer from `git clone` to a first authorized result in a few
  steps.

## Principles

1. **Simple beats complete.** Every file should read top to bottom for
   someone new to AAC. Prefer a few plain lines to a helper, and a named step
   to a clever construct.
2. **One concept at a time.** The README walks through the flow in the order
   it happens and points at the code for each step.
3. **Show AAC's security; add no security engineering of its own.** Pairing
   signatures, signed authority, published trust and the refused unsigned
   call are how AAC works, so the example shows them. Production hardening
   (read-only containers, dropped capabilities, secret stores) is not what
   the example teaches. It keeps only what running it requires: the
   containers run as you so they can read the key files the CLI creates.
4. **No reliability code.** No retries, recovery wrappers, guards for unusual
   setups or diagnostics commands. The two independent fictional tenants are
   the lesson, not a general multi-tenant deployment framework. When something goes
   wrong, the message from Docker or the CLI is the message; the README's
   short troubleshooting list covers the common cases.
5. **The CLI is the only generator.** The example never creates, copies or
   edits keys, certificates or the sidecar configuration. It reads what
   `aac init` wrote.
6. **Say what is left out.** The README names what the example does not show
   (production deployment, durable replay protection, retries, real bookings
   or payments, native Windows) and where that is documented.
7. **Tests keep the example working, nothing more.** The Compose file matches
   what the CLI writes, the agent refuses unsigned calls, the client runs the
   flow, and an opt-in live test measures the documented steps on a real
   tenant.

## Before adding something

Ask whether it helps a reader understand how AAC works. If it does not, leave
it out, or put it in the AAC documentation instead.
