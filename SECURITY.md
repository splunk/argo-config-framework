# Security Policy

## Project status

This project is an alpha reference implementation and does not currently
publish production-supported releases.

## Reporting a vulnerability

Do not open a public GitHub issue for a suspected vulnerability.

Report security concerns through
[Splunk Product Security](https://www.splunk.com/en_us/product-security.html).
Include a description of the impact, reproduction steps or a proof of concept,
and any relevant environment details.

## Deployment considerations

- Treat workflow submitters as trusted operators.
- Review generated WorkflowTemplates before applying them.
- Install the example in a dedicated namespace and reduce its RBAC permissions
  for your environment.
- Restrict who can submit workflows or change catalogs, adapters, and base
  templates.
- Use reviewed container images from a trusted registry.
- Do not place credentials, tokens, or sensitive URLs in workflow parameters,
  catalogs, or adapter files.
- Configure webhook authentication through Kubernetes Secrets or an
  environment-specific integration instead of embedding credentials in URLs.
