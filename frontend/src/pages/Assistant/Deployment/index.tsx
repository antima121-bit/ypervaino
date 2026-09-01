import { useState } from "react";
import TabHeader from "../components/TabHeader";
import TabNavigationBar from "../components/TabNavigationBar";
import { ReactComponent as AssistantDeploymentIcon } from "assets/assistant-deployment-icon.svg?react";
import { DeploymentNavigations } from "./config";
import Typography, { TypographyColors, TypographyVariants, TypographyWeights } from "aether/Typography";
import Chip, { ChipColors } from "aether/Chip";
import { assistantInfo } from "data/blueprint";

const deployment_header_title = "Deployment";
const deployment_header_description =
  "Manage your agent's go-live experience, configure channels, control availability, and publish updates.";

const cardStyle: React.CSSProperties = {
  background: "#FFF",
  border: "1px solid #E1DEDA",
  borderRadius: "8px",
  padding: "20px 24px",
  marginBottom: "16px",
};

const ChannelPane: React.FC<{ channel: "chat" | "voice" }> = ({ channel }) => {
  const df = assistantInfo.dialog_flow;
  const isActive = (df?.active_channels ?? []).includes(channel);

  return (
    <div style={cardStyle}>
      <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "12px" }}>
        <Typography variant={TypographyVariants.textLarge} weight={TypographyWeights.bold} style={{ textTransform: "capitalize" }}>
          {channel}
        </Typography>
        <Chip label={isActive ? "Active" : "Not deployed"} color={isActive ? ChipColors.success : ChipColors.default} />
      </div>
      {channel === "chat" ? (
        <>
          <Typography color={TypographyColors.subtle}>Trigger event: {df?.trigger_event ?? "—"}</Typography>
          <Typography color={TypographyColors.subtle}>Starting skill: {df?.starting_skill_name ?? "—"}</Typography>
        </>
      ) : (
        <>
          <Typography color={TypographyColors.subtle}>SIP URL: {assistantInfo.sip_url}</Typography>
          <Typography color={TypographyColors.subtle}>Runtime mode: {assistantInfo.runtime_mode}</Typography>
        </>
      )}
    </div>
  );
};

const PlaceholderPane: React.FC<{ label: string }> = ({ label }) => (
  <div style={{ ...cardStyle, textAlign: "center", color: "#B5B1AD", padding: "48px 24px" }}>
    Nothing to show for "{label}" in this mock preview.
  </div>
);

const Deployment: React.FC = () => {
  const [activePath, setActivePath] = useState("chat");

  return (
    <div style={{ width: "100%", display: "flex", flexDirection: "column", gap: "24px" }}>
      <TabHeader
        icon={<AssistantDeploymentIcon />}
        title={deployment_header_title}
        description={deployment_header_description}
      />

      <div style={{ display: "flex", flexDirection: "row", gap: "24px" }}>
        <TabNavigationBar navigations={DeploymentNavigations} activePath={activePath} onSelect={setActivePath} />

        <div style={{ flex: 1, marginBottom: "24px" }}>
          {activePath === "chat" && <ChannelPane channel="chat" />}
          {activePath === "voice" && <ChannelPane channel="voice" />}
          {activePath === "publish-and-go-live" && <PlaceholderPane label="Publish and go live" />}
          {activePath === "preview-and-share" && <PlaceholderPane label="Preview & Share" />}
        </div>
      </div>
    </div>
  );
};

export default Deployment;
