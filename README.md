# Original Xrypton Bot Source Code (xrypton.rf.gd)
the original xrypton bot source code v3.

Status: ACTIVE

## AntiNuke setup

Xrypton includes the `,antinuke` (` ,an` alias: `,an`) cog for audit-log based protection.
The bot role must have **View Audit Log**, moderation permissions for configured
punishments, and sufficient role hierarchy to act on offenders. The bot uses
`Intents.all()`, which includes the required guild, member, ban, and moderation
intents; enable the privileged Server Members intent in the Discord Developer
Portal as well. AntiNuke logs and configuration are retained for 14 days after
the module is disabled. V1 punishes and logs destructive actions but does not
attempt to automatically restore deleted channels, roles, or server settings.
