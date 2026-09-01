import Typography, {
  TypographyColors,
  TypographyVariants,
  TypographyWeights,
} from "aether/Typography";
import { useTabHeaderStyles as useStyles } from "./styles";

interface Props {
  icon: React.ReactNode;
  title: string;
  description: string;
}

const TabHeader: React.FC<Props> = ({ icon: Icon, title, description }) => {
  const classes = useStyles();

  return (
    <div className={classes.tabHeaderContainer}>
      <div className={classes.headerIconContainer}>{Icon}</div>

      <div>
        <Typography variant={TypographyVariants.textXL} weight={TypographyWeights.bold}>
          {title}
        </Typography>
        <Typography weight={TypographyWeights.medium} color={TypographyColors.subtle}>
          {description}
        </Typography>
      </div>
    </div>
  );
};

export default TabHeader;
