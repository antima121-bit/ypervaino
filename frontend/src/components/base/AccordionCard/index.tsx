import type React from "react";
import { makeStyles } from "@mui/styles";
import Accordion, { type AccordionProps } from "@mui/material/Accordion";
import AccordionSummary from "@mui/material/AccordionSummary";
import AccordionDetails from "@mui/material/AccordionDetails";
import { ReactComponent as ChevronDown } from "assets/chevron-down.svg?react";
import Typography, { TypographyVariants, TypographyWeights } from "aether/Typography";
import { useCallback, useEffect, useState } from "react";

export interface AccordionCardProps
  extends Omit<AccordionProps, "content" | "children"> {
  title: string;
  subtitle?: string | React.ReactNode;
  icon?: React.ReactNode;
  titleCount?: number;
  content: React.ReactNode;
  headerButtons?: React.ReactNode;
  rightContent?: React.ReactNode;
  contentStyle?: React.CSSProperties;
  disableToggle?: boolean;
  expandLocked?: boolean;
  autoExpand?: boolean;
}

const useStyles = makeStyles(() => ({
  "accordion-card": {
    "&.MuiAccordion-root": {
      padding: "0px",
      justifyContent: "space-between",
      borderRadius: "8px",
      background: "#FFF",
      boxShadow:
        "0px 1px 3px 0px rgba(16, 24, 40, 0.10), 0px 1px 2px 0px rgba(16, 24, 40, 0.06)",

      "&:first-of-type": {
        borderTopLeftRadius: "8px",
        borderTopRightRadius: "8px",
      },
      "&:last-of-type": {
        borderBottomLeftRadius: "8px",
        borderBottomRightRadius: "8px",
      },

      "&:before": {
        content: "none",
        opacity: 0,
        height: 0,
      },
    },
    "& .MuiAccordionSummary-root": {
      padding: "16px 24px",
      backgroundColor: "#FFF",
      alignItems: "center",

      "& .MuiAccordionSummary-content": {
        margin: 0,
        alignItems: "center",
      },

      "& .MuiAccordionSummary-expandIconWrapper": {
        alignSelf: "center",
      },
    },

    "& .accordion-card-icon": {
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      flexShrink: 0,
      "& svg": {
        display: "block",
      },
    },
    "& .MuiCollapse-root": {
      backgroundColor: "#FFF",
      "& .MuiAccordionDetails-root": {
        padding: "24px",
        backgroundColor: "#FFF",
        borderBottomLeftRadius: "8px",
        borderBottomRightRadius: "8px",
      },
    },
    "&.Mui-expanded": {
      margin: 0,
    },
  },
  titleCountBadge: {
    backgroundColor: "#F3F2F0",
    borderRadius: "16px",
    padding: "2px 12px",
    fontSize: "12px",
    fontWeight: 600,
    lineHeight: "20px",
    color: "#282624",
    whiteSpace: "nowrap",
  },
  titleRow: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
  },
}));

const AccordionCard: React.FC<AccordionCardProps> = ({
  title,
  subtitle,
  icon,
  titleCount,
  content,
  headerButtons,
  rightContent,
  defaultExpanded = false,
  contentStyle,
  disableToggle = false,
  expandLocked = false,
  autoExpand = false,
  ...props
}) => {
  const classes = useStyles();

  const [expand, setExpand] = useState(defaultExpanded);
  const expandedState = disableToggle ? true : expand;

  useEffect(() => {
    if (expandLocked) {
      setExpand(false);
    }
  }, [expandLocked]);

  useEffect(() => {
    if (autoExpand && !expandLocked) {
      setExpand(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoExpand]);

  const handleClickAccordion = useCallback(
    (event: any): void => {
      if (disableToggle || expandLocked) {
        return;
      }
      event.stopPropagation();
      const targetClassList = event.target.classList;

      if (targetClassList.contains("MuiButton-root")) {
        return;
      }

      setExpand((prev) => !prev);
    },
    [expand, disableToggle, expandLocked]
  );

  return (
    <Accordion
      {...props}
      expanded={expandedState}
      className={classes["accordion-card"]}
    >
      <AccordionSummary
        expandIcon={disableToggle ? null : <ChevronDown />}
        onClick={handleClickAccordion}
      >
        <div style={{ width: "100%", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", justifyContent: "flex-start", alignItems: "center", columnGap: "16px" }}>
            {icon && <div className="accordion-card-icon">{icon}</div>}
            <div style={{ display: "flex", flexDirection: "column" }}>
              <div className={classes.titleRow}>
                <Typography variant={TypographyVariants.textXL} weight={TypographyWeights.semiBold}>
                  {title}
                </Typography>
                {titleCount != null && (
                  <span className={classes.titleCountBadge}>{titleCount}</span>
                )}
              </div>
              {subtitle &&
                (typeof subtitle === "string" ? subtitle.trim() !== "" : true) && (
                  <Typography weight={TypographyWeights.medium} sx={{ color: "#7C7972" }}>
                    {subtitle}
                  </Typography>
                )}
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", columnGap: "16px", marginRight: "16px" }}>
            {rightContent && rightContent}
            {headerButtons && <div>{headerButtons}</div>}
          </div>
        </div>
      </AccordionSummary>

      <AccordionDetails style={contentStyle ?? {}}>{content}</AccordionDetails>
    </Accordion>
  );
};

export default AccordionCard;
