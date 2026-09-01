import { IconButton, Tooltip } from "@mui/material";
import { useAssistantHeaderStyles as useStyles } from "../styles";
import { ReactComponent as ArrowLeft } from "assets/arrow-left.svg?react";
import Typography, { TypographyVariants, TypographyWeights } from "aether/Typography";
import AssistantNavigationBar from "./AssistantNavigation";
import { type AssistantRoute } from "pages/Assistant/types";

interface Props {
  children: React.ReactNode;
  title: string;
  description?: string;
  publishChips?: React.ReactNode;
  showTitle?: boolean;
  showNavigation?: boolean;
  currentTab: AssistantRoute;
  onSelectTab: (key: AssistantRoute) => void;
}

const AssistantHeader: React.FC<Props> = ({
  children,
  title,
  description = "",
  publishChips,
  showTitle = true,
  showNavigation = true,
  currentTab,
  onSelectTab,
}) => {
  const classes = useStyles();

  return (
    <div className={classes.assistantHeaderContainer}>
      <div className={classes.assistantDetailsContainer}>
        <div className="center">
          <IconButton className="back-button" disabled>
            <ArrowLeft />
          </IconButton>
        </div>

        <div className={classes.assistantTitleContainer}>
          {showTitle && (
            <>
              <div style={{ display: "flex", alignItems: "center", minWidth: 0 }}>
                <Tooltip title={title} placement="top">
                  <span style={{ display: "flex", minWidth: 0, overflow: "hidden" }}>
                    <Typography variant={TypographyVariants.textXL} weight={TypographyWeights.bold} renderInLines={1}>
                      {title}
                    </Typography>
                  </span>
                </Tooltip>
                {publishChips}
              </div>
              {description && (
                <Typography weight={TypographyWeights.medium} renderInLines={1}>
                  {description}
                </Typography>
              )}
            </>
          )}
        </div>
      </div>

      {showNavigation && (
        <div className={classes.assistantNavigationContainer}>
          <AssistantNavigationBar currentTab={currentTab} onSelectTab={onSelectTab} />
        </div>
      )}

      <div className={classes.assistantActionContainer}>{children}</div>
    </div>
  );
};

export default AssistantHeader;
