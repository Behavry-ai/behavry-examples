# Example policy: the MSP gateway

One Rego module governs the MSP gateway both MSP examples use. Behavry resolves
which system each tool call reaches (Halo, Meraki, the RMM, Microsoft 365) from
the tool name, and this policy decides per tool:

| Outcome | Tools |
| --- | --- |
| Allowed | Reads, PSA notes and tickets, licence assignment, standard groups, blocking sign-in, ending sessions, model calls for the example agents |
| Held for a person | Ticket merge and delete, device reboot, RMM scripts, creating an account, adding a non-standard group, converting a mailbox, removing licences |
| Refused | Wiping a device, assigning a directory role, deleting an account |

Load it as a tenant policy (Policies, New Policy, Rego Editor). It answers
only for the gateway named in `_example_gateway` and for the agent ids in
`_example_agents`, so it does not change decisions for anything else.

Test it with OPA:

```bash
opa test policies/
```
