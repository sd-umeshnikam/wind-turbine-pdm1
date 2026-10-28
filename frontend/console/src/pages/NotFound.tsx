import { Link } from "react-router-dom";
import { Empty } from "../components/ui";

export function NotFound() {
  return (
    <Empty title="Page not found">
      <Link to="/">Back to the fleet overview</Link>
    </Empty>
  );
}
