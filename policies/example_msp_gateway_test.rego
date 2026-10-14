package behavry.authz_test

import data.behavry.authz
import rego.v1

_in(tool, params) := {
	"request": {"mcp_server": "example-msp-gateway", "tool_name": tool, "parameters": params},
	"agent": {"permissions": [], "roles": []},
}

test_note_allowed if authz.decision.result == "allow" with input as _in("halo_add_action", {})
test_reboot_held if authz.decision.result == "escalate" with input as _in("meraki_reboot_device", {})
test_wipe_refused if authz.decision.result == "deny" with input as _in("rmm_wipe_device", {})
test_create_user_held if authz.decision.result == "escalate" with input as _in("m365_create_user", {})
test_standard_group_allowed if authz.decision.result == "allow" with input as _in("m365_add_group_member", {"group": "Clinical"})
test_other_group_held if authz.decision.result == "escalate" with input as _in("m365_add_group_member", {"group": "Domain Admins"})
test_containment_allowed if authz.decision.result == "allow" with input as _in("m365_disable_user", {})
test_unmapped_held if authz.decision.result == "escalate" with input as _in("halo_something_new", {})
test_other_servers_untouched if not authz.decision with input as {"request": {"mcp_server": "web-api", "tool_name": "http_get", "parameters": {}}}

test_example_model_call_allowed if {
	authz.decision.result == "allow" with input as {"request": {"mcp_server": "anthropic-proxy", "tool_name": "anthropic-api", "action": "POST", "resource": "/anthropic/v1/messages", "parameters": {}}, "agent": {"id": "<meraki-triage-agent-id>", "permissions": [], "roles": []}}
}

test_other_agents_model_calls_untouched if {
	not authz.decision with input as {"request": {"mcp_server": "anthropic-proxy", "tool_name": "anthropic-api", "action": "POST", "resource": "/anthropic/v1/messages", "parameters": {}}, "agent": {"id": "someone-else", "permissions": [], "roles": []}}
}
