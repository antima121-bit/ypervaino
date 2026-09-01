import AssistantGuidelines from "../Guidelines";
import AssistantWorkflows from "../Workflows";
import { getBuildPageCapabilities } from "./util";
import { assistantInfo } from "data/blueprint";
import { OrchestrationType } from "../types";

const AssistantBuilder: React.FC = () => {
  const orchestrationType = assistantInfo.orchestration_type as OrchestrationType;
  const capabilities = getBuildPageCapabilities(orchestrationType);

  return (
    <div style={{ display: "flex", flexDirection: "column", rowGap: "16px", maxWidth: "1040px", margin: "0 auto" }}>
      <AssistantGuidelines />
      <AssistantWorkflows enableDialogFlow={capabilities.enableDialogFlow} />
    </div>
  );
};

export default AssistantBuilder;
