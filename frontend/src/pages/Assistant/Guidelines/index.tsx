import AccordionCard from "components/base/AccordionCard";
import { ReactComponent as AssistantGuidelinesIcon } from "assets/guidelines-rule-icon.svg?react";
import { ReactComponent as BehaviourIcon } from "assets/message-text-square.svg?react";
import { ReactComponent as GeneralPurposeIcon } from "assets/building-07.svg?react";
import Typography, { TypographyColors, TypographyWeights } from "aether/Typography";
import { assistantInfo } from "data/blueprint";

const guidelines_title = "Basic details and guidelines";
const guidelines_subtitle = "Define the agent's objective and provide business context";

const ReadOnlyText: React.FC<{ text: string }> = ({ text }) =>
  text ? (
    <Typography style={{ whiteSpace: "pre-wrap", lineHeight: "24px" }}>{text}</Typography>
  ) : (
    <Typography color={TypographyColors.subtle}>Not provided.</Typography>
  );

const GuidelinesContent: React.FC = () => {
  const ext = assistantInfo.external_instructions_given_to_bot;

  return (
    <div style={{ display: "flex", flexDirection: "column", rowGap: "16px" }}>
      <AccordionCard
        title="Goal and company context"
        subtitle="Configure personality of your voice agent"
        icon={<GeneralPurposeIcon />}
        content={
          <div style={{ display: "flex", flexDirection: "column", rowGap: "24px" }}>
            <div>
              <Typography weight={TypographyWeights.bold} style={{ marginBottom: "8px" }}>Goal</Typography>
              <ReadOnlyText text={ext.goal} />
            </div>
            <div>
              <Typography weight={TypographyWeights.semiBold} style={{ marginBottom: "8px" }}>Company info</Typography>
              <ReadOnlyText text={ext.company_info_text} />
            </div>
          </div>
        }
      />
      <AccordionCard
        title="Behaviour and tone"
        subtitle="Shape how the agent talks and responds — tone, style, fallbacks, and handoff cues."
        icon={<BehaviourIcon />}
        content={<ReadOnlyText text={ext.guidelines_and_rules} />}
      />
    </div>
  );
};

const Guidelines: React.FC = () => {
  return (
    <AccordionCard
      defaultExpanded={true}
      title={guidelines_title}
      subtitle={guidelines_subtitle}
      icon={<AssistantGuidelinesIcon />}
      content={<GuidelinesContent />}
      contentStyle={{ backgroundColor: "#FFF8F2" }}
    />
  );
};

export default Guidelines;
