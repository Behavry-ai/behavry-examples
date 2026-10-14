package behavry.authz

import rego.v1

# Behavry examples: policy for the example MSP gateway, which fronts Halo,
# Meraki, an RMM and Microsoft 365 behind one registration. Behavry resolves
# the downstream system from the tool name into input.request.backend_system.
#
# `decision` is a complete rule in this package, so this module claims the
# gateway outright (_has_specific_server_policy keeps the generic fallback
# away) and answers exactly once through an else chain.

# The name your gateway is registered under in Behavry.
_example_gateway := "example-msp-gateway"

_is_example_gateway if input.request.mcp_server == _example_gateway

_has_specific_server_policy if _is_example_gateway

decision := _msp_decision if _is_example_gateway

# Refused outright.
_msp_refused := {
	"rmm_wipe_device", "m365_add_directory_role", "m365_delete_user",
}

# Held for a person.
_msp_held := {
	"halo_merge_ticket", "halo_delete_ticket",
	"meraki_reboot_device",
	"rmm_reboot_device", "rmm_run_script",
	"m365_create_user", "m365_convert_mailbox_to_shared", "m365_remove_licenses",
}

# Allowed: reads, PSA notes and tickets, licence and standard-group grants for
# a new starter, and the leaver containment steps (block sign-in, end sessions).
_msp_allowed := {
	"halo_search_assets", "halo_list_tickets_by_client", "halo_create_ticket",
	"halo_update_ticket", "halo_add_action",
	"meraki_get_device",
	"m365_get_user", "m365_assign_license", "m365_disable_user", "m365_revoke_sessions",
}

# Group membership is allowed only for the client's standard groups.
_standard_groups := {"All Staff", "Front Desk", "Clinical", "Practice Management", "Billing"}

_msp_tool := input.request.tool_name

_msp_decision := {
	"result": "deny", "reason": "Not permitted for agents through the MSP gateway",
	"policy": "examples.msp_gateway.refused",
} if {
	_msp_tool in _msp_refused
} else := {"result": "allow", "policy": "examples.msp_gateway.standard_group"} if {
	_msp_tool == "m365_add_group_member"
	input.request.parameters.group in _standard_groups
} else := {
	"result": "escalate", "reason": "Group outside the standard list needs approval",
	"policy": "examples.msp_gateway.group_review",
} if {
	_msp_tool == "m365_add_group_member"
} else := {
	"result": "escalate", "reason": "This action changes a client system and needs a person's approval",
	"policy": "examples.msp_gateway.held",
} if {
	_msp_tool in _msp_held
} else := {"result": "allow", "policy": "examples.msp_gateway.allowed"} if {
	_msp_tool in _msp_allowed
} else := {
	"result": "escalate", "reason": "Unmapped tool on the MSP gateway needs approval",
	"policy": "examples.msp_gateway.unmapped",
}

# Model calls for the example agents only, through Behavry's Anthropic proxy.
# Replace these with your agents' Behavry ids (Agents page, or the provision
# response). Your plane's own roles may already allow model calls, in which
# case drop this block.
_example_agents := {"<meraki-triage-agent-id>", "<m365-lifecycle-agent-id>"}

_is_example_model_call if {
	input.agent.id in _example_agents
	input.request.mcp_server == "anthropic-proxy"
}

_has_specific_server_policy if _is_example_model_call

decision := {"result": "allow", "policy": "examples.model_calls"} if _is_example_model_call
