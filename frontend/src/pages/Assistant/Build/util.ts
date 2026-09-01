import { OrchestrationType } from "../types";

export interface BuildPageCapabilities {
  showKnowledge: boolean;
  showAgents: boolean;
  showSingleAgentCentralPiece: boolean;
  enableDialogFlow: boolean;
}

const LEGACY_CAPABILITIES: BuildPageCapabilities = {
  showKnowledge: true,
  showAgents: true,
  showSingleAgentCentralPiece: false,
  enableDialogFlow: true,
};

export const BUILD_PAGE_CAPABILITIES: Record<OrchestrationType, BuildPageCapabilities> = {
  [OrchestrationType.DELEGATOR_V2_VOICE]: LEGACY_CAPABILITIES,
  [OrchestrationType.SIMPLE]: LEGACY_CAPABILITIES,
  [OrchestrationType.DIALOG_FLOW]: LEGACY_CAPABILITIES,
  [OrchestrationType.SINGLE_AGENT]: {
    showKnowledge: false,
    showAgents: false,
    showSingleAgentCentralPiece: true,
    enableDialogFlow: false,
  },
  [OrchestrationType.MULTI_AGENT]: {
    showKnowledge: false,
    showAgents: true,
    showSingleAgentCentralPiece: false,
    enableDialogFlow: false,
  },
  [OrchestrationType.WORKFLOW_AGENT]: {
    showKnowledge: false,
    showAgents: false,
    showSingleAgentCentralPiece: false,
    enableDialogFlow: true,
  },
};

export const getBuildPageCapabilities = (
  orchestrationType: OrchestrationType | null | undefined
): BuildPageCapabilities =>
  orchestrationType
    ? BUILD_PAGE_CAPABILITIES[orchestrationType]
    : BUILD_PAGE_CAPABILITIES[OrchestrationType.DELEGATOR_V2_VOICE];
