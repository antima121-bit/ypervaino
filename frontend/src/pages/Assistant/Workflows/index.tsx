import AccordionCard from "components/base/AccordionCard";
import { ReactComponent as WorkflowIcon } from "assets/workflow.svg?react";
import { ReactComponent as PhoneIcon } from "assets/phone-icon.svg?react";
import Button, { ButtonSizes, ButtonVariants } from "aether/Button";
import Chip, { ChipColors, ChipSizes } from "aether/Chip";
import Typography, { TypographyColors, TypographyVariants, TypographyWeights } from "aether/Typography";
import { Table, TableBody, TableCell, TableContainer, TableHead, TableRow } from "@mui/material";
import { assistantInfo } from "data/blueprint";

const workflows_title = "Workflows";
const workflows_subtitle = "Automate multi-step processes and connect different systems";

const preAndPostWorkflowsTitle = "Pre and post conversation workflows";
const preAndPostWorkflowsSubTitle =
  "Build flows to tackle the tasks you want to execute before and after the conversation ends";

const TRIGGER_EVENT_LABELS: Record<string, string> = {
  CONVERSATION_START: "Conversation starts",
  CONVERSATION_END: "Conversation ends",
};

interface WorkflowsProps {
  enableDialogFlow: boolean;
}

const Workflows: React.FC<WorkflowsProps> = ({ enableDialogFlow }) => {
  const df = assistantInfo.dialog_flow;
  const nodes = df?.nodes ?? [];
  const triggerLabel = TRIGGER_EVENT_LABELS[df?.trigger_event] ?? df?.trigger_event ?? "—";

  return (
    <AccordionCard
      defaultExpanded={true}
      title={enableDialogFlow ? workflows_title : preAndPostWorkflowsTitle}
      subtitle={enableDialogFlow ? workflows_subtitle : preAndPostWorkflowsSubTitle}
      icon={<WorkflowIcon />}
      headerButtons={
        <Button variant={ButtonVariants.outlined} size={ButtonSizes.xsmall} disabled>
          Add a new workflow
        </Button>
      }
      contentStyle={{ backgroundColor: "#FFF8F2" }}
      content={
        <TableContainer>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>Workflows</TableCell>
                <TableCell>Trigger event</TableCell>
                <TableCell>Last edited</TableCell>
                <TableCell>Status</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {nodes.map((node) => {
                const isStart = df.starting_skill_name === node.skill_name;
                return (
                  <TableRow key={node.node_id}>
                    <TableCell>
                      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                        <Typography weight={TypographyWeights.semiBold}>{node.display_name}</Typography>
                        {(df.active_channels ?? []).includes("voice") && (
                          <PhoneIcon style={{ width: 16, height: 16 }} />
                        )}
                        {isStart && <Chip label="Start" size={ChipSizes.xsmall} color={ChipColors.success} />}
                      </div>
                      <Typography variant={TypographyVariants.textSmall} color={TypographyColors.subtle}>
                        {(node.transition_targets ?? []).join(" → ") || "No transitions"}
                      </Typography>
                    </TableCell>
                    <TableCell>{triggerLabel}</TableCell>
                    <TableCell>Aug 28, 2026</TableCell>
                    <TableCell>
                      <Chip label="Ready" color={ChipColors.success} />
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      }
    />
  );
};

export default Workflows;
