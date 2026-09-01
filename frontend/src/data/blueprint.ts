import raw from "./va_blueprint_resound.json";

export interface DialogFlowNode {
  node_id: string;
  display_name: string;
  skill_name: string;
  llmagent_id: string;
  transition_targets: string[];
}

export interface DialogFlow {
  flow_id: string;
  name: string;
  enabled: boolean;
  trigger_event: string;
  active_channels: string[];
  starting_node_id: string;
  starting_skill_name: string;
  nodes: DialogFlowNode[];
  edges: Array<{ source: string; target: string }>;
}

export interface AssistantInfo {
  tenant: string;
  assistant_id: string;
  origin_id: string;
  runtime_mode: string;
  orchestration_type: string;
  effective_orchestration_type: string;
  has_skills: boolean;
  skill_list: Array<{ name: string; id: string; description: string; instructions: string }>;
  has_policy_based_skill: boolean;
  has_knowledge: boolean;
  kb_resource_ids: string[];
  atlas_resource_ids: string[];
  external_instructions_given_to_bot: {
    guidelines_and_rules: string;
    company_info_text: string;
    goal: string;
  };
  sip_url: string;
  dialog_flow: DialogFlow;
}

export interface StructuredSkill {
  skill_id: string;
  skill_name: string;
  original_instructions_by_user: string;
  structured_instructions_with_tools: string;
  structured_instructions_without_tools: string;
}

interface BlueprintPayload {
  success: boolean;
  data: {
    assistant_info: AssistantInfo;
    structured_skill_description_map: Record<string, StructuredSkill>;
  };
  message: string;
}

const blueprint = raw as unknown as BlueprintPayload;

export const assistantInfo: AssistantInfo = blueprint.data.assistant_info;
export const structuredSkills = blueprint.data.structured_skill_description_map;

export default blueprint;
