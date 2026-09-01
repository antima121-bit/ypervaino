import { useState } from "react";
import NavigationBar from "layout/components/NavigationBar";
import AssistantHeader from "./components/AssistantHeader";
import Button, { ButtonVariants, ButtonSizes } from "aether/Button";
import Chip, { ChipColors } from "aether/Chip";
import { AssistantRoute } from "./types";
import AssistantBuilder from "./Build";
import Deployment from "./Deployment";
import Tools from "./Tools";
import Ypervaino from "./Ypervaino";
import { assistantInfo } from "data/blueprint";

const TAB_CONTENT: Record<AssistantRoute, React.FC> = {
  [AssistantRoute.OVERVIEW]: AssistantBuilder,
  [AssistantRoute.DEPLOYMENT]: Deployment,
  [AssistantRoute.TOOLS]: Tools,
  [AssistantRoute.YPERVAINO]: Ypervaino,
};

const titleCase = (s: string): string =>
  (s || "").replace(/[-_]/g, " ").replace(/\w\S*/g, (w) => w[0].toUpperCase() + w.slice(1).toLowerCase());

const Assistant: React.FC = () => {
  const [currentTab, setCurrentTab] = useState<AssistantRoute>(AssistantRoute.OVERVIEW);
  const ActiveContent = TAB_CONTENT[currentTab];

  return (
    <div>
      <NavigationBar />

      <div style={{ marginInlineStart: "72px" }}>
        <AssistantHeader
          title={titleCase(assistantInfo.tenant)}
          description="automation bot"
          currentTab={currentTab}
          onSelectTab={setCurrentTab}
          publishChips={
            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginLeft: "12px" }}>
              <Chip label="Live" color={ChipColors.success} startIcon={<span style={{ fontSize: "10px" }}>▶</span>} />
              <Chip label="Unpublished Changes" color={ChipColors.warning} />
            </div>
          }
        >
          <Button variant={ButtonVariants.outlined} size={ButtonSizes.small}>
            Test 🧪
          </Button>
        </AssistantHeader>

        <div style={{ paddingTop: "104px", padding: "104px 32px 40px", minWidth: "1200px" }}>
          <ActiveContent />
        </div>
      </div>
    </div>
  );
};

export default Assistant;
