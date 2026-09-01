import { useState } from "react";
import TabHeader from "../components/TabHeader";
import TabNavigationBar from "../components/TabNavigationBar";
import { ReactComponent as AssistantToolsIcon } from "assets/assistant-tools-icon.svg?react";
import { getToolsNavigations } from "./config";
import Typography, { TypographyColors } from "aether/Typography";

const tools_header_title = "Tools & Settings";
const tools_header_description =
  "APIs, flows, system tools, variables, and guardrails for how this assistant runs and what it can do.";

const EmptyState: React.FC<{ label: string }> = ({ label }) => (
  <div
    style={{
      background: "#FFF",
      border: "1px solid #E1DEDA",
      borderRadius: "8px",
      padding: "48px 24px",
      textAlign: "center",
    }}
  >
    <Typography color={TypographyColors.subtle}>No {label.toLowerCase()} configured for this assistant.</Typography>
  </div>
);

const Tools: React.FC = () => {
  const toolsNavigations = getToolsNavigations();
  const [activePath, setActivePath] = useState("apis");
  const activeLabel = toolsNavigations.flatMap((c) => c.paths).find((p) => p.path === activePath)?.title ?? "items";

  return (
    <div style={{ width: "100%", display: "flex", flexDirection: "column", gap: "24px" }}>
      <TabHeader icon={<AssistantToolsIcon />} title={tools_header_title} description={tools_header_description} />

      <div style={{ display: "flex", flexDirection: "row", gap: "24px" }}>
        <TabNavigationBar navigations={toolsNavigations} activePath={activePath} onSelect={setActivePath} />

        <div style={{ flex: 1 }}>
          <EmptyState label={activeLabel} />
        </div>
      </div>
    </div>
  );
};

export default Tools;
