import clsx from "clsx";
import { ReactComponent as LevelLogo } from "assets/level/level-logo-light.svg?react";
import NavigationItems from "./config";
import useStyles from "./style";
import Typography, {
  TypographyColors,
  TypographyVariants,
  TypographyWeights,
} from "aether/Typography";

const NavigationBar: React.FC = () => {
  const classes = useStyles();
  const activePath = "assistant";

  return (
    <div className={classes["navbar-container"]}>
      <div className={classes["navbar-logo-container"]}>
        <LevelLogo />
      </div>

      <div className={classes["navbar-item-container"]}>
        {NavigationItems.map(({ key, path, title, icon: NavigationIcon, enable }) => (
          <div
            className={clsx("navbar-item", {
              active: path === activePath,
              hidden: !enable,
            })}
            key={key}
          >
            <div className="navbar-item-icon-container">
              <NavigationIcon className="navbar-item-icon" />
            </div>

            <Typography
              className="item-display-name"
              variant={TypographyVariants.textTiny}
              weight={path === activePath ? TypographyWeights.bold : TypographyWeights.medium}
              color={path === activePath ? TypographyColors.white : TypographyColors.placeholder}
            >
              {title}
            </Typography>
          </div>
        ))}
      </div>
    </div>
  );
};

export default NavigationBar;
