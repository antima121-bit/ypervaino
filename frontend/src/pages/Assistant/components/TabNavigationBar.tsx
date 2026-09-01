import Typography, { TypographyVariants, TypographyWeights } from "aether/Typography";
import { useTabNavigationStyles as useStyles } from "./styles";
import clsx from "clsx";
import React from "react";
import { type TabNavigationCategory } from "../types";

interface Props {
  navigations: TabNavigationCategory[];
  activePath: string;
  onSelect?: (path: string) => void;
}

const TabNavigationBar: React.FC<Props> = ({ navigations, activePath, onSelect }) => {
  const classes = useStyles();

  return (
    <div className={classes.tabNavigationContainer}>
      {navigations.map(({ key, title, paths }, categoryIndex) => (
        <React.Fragment key={key}>
          <div className={classes.categoryContainer}>
            {title && (
              <div className="category-title-container">
                <Typography variant={TypographyVariants.textLarge} weight={TypographyWeights.bold}>
                  {title}
                </Typography>
              </div>
            )}

            <div className={classes.categoryNavigationsContainer}>
              {paths.map(({ path, title: pathTitle, key: pathKey, enabled, icon: CategoryIcon }) => {
                const isActive = activePath === path;
                if (!enabled) return null;

                return (
                  <div
                    key={pathKey}
                    onClick={() => enabled && onSelect?.(path)}
                    className={clsx("navigation-link-container", {
                      active: isActive,
                      disabled: !enabled,
                    })}
                  >
                    {CategoryIcon && (
                      <CategoryIcon
                        className={clsx(classes.categoryIcon, {
                          [classes.categoryIconActive]: isActive,
                        })}
                      />
                    )}
                    <Typography
                      weight={TypographyWeights.semiBold}
                      className={clsx({ [classes.categoryTitleActive]: isActive })}
                    >
                      {pathTitle}
                    </Typography>
                  </div>
                );
              })}
            </div>
          </div>
          {categoryIndex < navigations.length - 1 && (
            <div className={classes.categorySeparator}></div>
          )}
        </React.Fragment>
      ))}
    </div>
  );
};

export default TabNavigationBar;
