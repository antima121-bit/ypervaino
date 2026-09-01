import React from "react";
import Typography, { TypographyWeights } from "aether/Typography";
import { useAssistantNavigationStyles as useStyles } from "../styles";
import clsx from "clsx";
import { type AssistantRoute } from "pages/Assistant/types";
import { AssistantNavigations } from "pages/Assistant/config";

interface Props {
  currentTab: AssistantRoute;
  onSelectTab: (key: AssistantRoute) => void;
}

const AssistantNavigationBar: React.FC<Props> = ({ currentTab, onSelectTab }) => {
  const classes = useStyles();

  return (
    <div className={classes.assistantNavigationContainer}>
      {AssistantNavigations.map(({ label, key, icon: Icon }, index) => {
        return (
          <React.Fragment key={key}>
            <div
              className={clsx(classes.navigationItemContainer, {
                active: key === currentTab,
              })}
              onClick={() => onSelectTab(key)}
            >
              <div className="navigation-item-content">
                {Icon && <div className={classes.navigationItemIcon}>{Icon}</div>}
                <div className={classes.navigationItemLabel}>
                  <Typography weight={TypographyWeights.semiBold}>{label}</Typography>
                </div>
              </div>
            </div>
            {index === 1 && <div className={classes.overviewSeparator}></div>}
          </React.Fragment>
        );
      })}
    </div>
  );
};

export default AssistantNavigationBar;
