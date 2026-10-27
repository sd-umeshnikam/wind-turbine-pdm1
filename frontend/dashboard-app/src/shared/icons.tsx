// Inline stroke icons (no icon-font dependency). They inherit currentColor.
import type { SVGProps } from "react";

function Icon({ children, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  );
}

export const IconTurbine = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <circle cx="12" cy="9" r="1.6" />
    <path d="M12 7.4 11 2.5c1.6-.4 2.6.8 2.3 2.3L12 7.4M13.4 9.8l4.3 2.6c-.9 1.4-2.5 1.3-3.2 0l-1.1-2.6M10.6 9.8l-4.3 2.6c.9 1.4 2.5 1.3 3.2 0l1.1-2.6M12 10.6V21.5M9 21.5h6" />
  </Icon>
);
export const IconGrid = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <rect x="3.5" y="3.5" width="7" height="7" rx="1.5" />
    <rect x="13.5" y="3.5" width="7" height="7" rx="1.5" />
    <rect x="3.5" y="13.5" width="7" height="7" rx="1.5" />
    <rect x="13.5" y="13.5" width="7" height="7" rx="1.5" />
  </Icon>
);
export const IconBell = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15Z" />
    <path d="M10 20.5a2.2 2.2 0 0 0 4 0" />
  </Icon>
);
export const IconActivity = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M3 12h4l2.5-6 5 12 2.5-6h4" />
  </Icon>
);
export const IconCube = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M12 3 20 7.5v9L12 21l-8-4.5v-9Z" />
    <path d="M4 7.5 12 12l8-4.5M12 12v9" />
  </Icon>
);
export const IconTrend = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M3.5 17 9 11.5l4 4L20.5 8" />
    <path d="M15 8h5.5v5.5" />
  </Icon>
);
export const IconSliders = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0" />
    <circle cx="16" cy="6" r="2" />
    <circle cx="10" cy="12" r="2" />
    <circle cx="18" cy="18" r="2" />
  </Icon>
);
export const IconMenu = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M4 7h16M4 12h16M4 17h16" />
  </Icon>
);
export const IconClose = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M6 6l12 12M18 6 6 18" />
  </Icon>
);
