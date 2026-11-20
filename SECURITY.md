# Security policy

## Reporting a vulnerability

Please do not open a public issue for a suspected credential leak or security
vulnerability. Contact the repository owner privately through GitHub so the
issue can be investigated without disclosing sensitive information.

Never commit API tokens, Signal credentials, Mealie credentials, private keys,
queue databases, downloaded media, or raw recipe evidence containing private
content. Keep deployment secrets in the host's secret-management system.

The queue API is intended to run on a private network and must be protected by
`QUEUE_TOKEN` before it is exposed beyond localhost or a trusted deployment
network.
