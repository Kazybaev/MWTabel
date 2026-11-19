import {
  CategoryScale,
  Chart,
  Filler,
  Legend,
  LinearScale,
  LineController,
  LineElement,
  PointElement,
  Tooltip,
} from "chart.js";

Chart.register(CategoryScale, LinearScale, PointElement, LineElement, LineController, Filler, Tooltip, Legend);

export { Chart };
