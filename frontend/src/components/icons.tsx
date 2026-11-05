import type { SVGProps } from 'react';

type IconProps = SVGProps<SVGSVGElement>;

const base = (props: IconProps): IconProps => ({
  className: ['ui-icon', props.className].filter(Boolean).join(' '),
  viewBox: '0 0 24 24',
  'aria-hidden': true,
  focusable: false,
  ...props,
});

export const CheckIcon = (p: IconProps) => (
  <svg {...base(p)}>
    <polyline points="20 6 9 17 4 12" />
  </svg>
);

export const CloseIcon = (p: IconProps) => (
  <svg {...base(p)}>
    <line x1="18" y1="6" x2="6" y2="18" />
    <line x1="6" y1="6" x2="18" y2="18" />
  </svg>
);

export const ExportIcon = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
    <polyline points="7 10 12 15 17 10" />
    <line x1="12" y1="15" x2="12" y2="3" />
  </svg>
);

export const WarningIcon = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
    <line x1="12" y1="9" x2="12" y2="13" />
    <line x1="12" y1="17" x2="12.01" y2="17" />
  </svg>
);

export const RefreshIcon = (p: IconProps) => (
  <svg {...base(p)}>
    <polyline points="23 4 23 10 17 10" />
    <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
  </svg>
);

export const EditIcon = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M12 20h9" />
    <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
  </svg>
);

export const LogoIcon = EditIcon;
export const SendIcon = CheckIcon;
export const StopIcon = CloseIcon;
export const PlusIcon = RefreshIcon;
export const SunIcon = EditIcon;
export const MoonIcon = EditIcon;
export const ThumbUpIcon = CheckIcon;
export const ThumbDownIcon = CloseIcon;
export const CheckCircleIcon = CheckIcon;
export const AlertIcon = WarningIcon;
export const ShieldIcon = WarningIcon;
export const ClockIcon = RefreshIcon;
export const ChevronIcon = EditIcon;
export const ExternalLinkIcon = ExportIcon;
export const ToolIcon = EditIcon;
export const DatabaseIcon = ExportIcon;
export const ArrowRightLeftIcon = RefreshIcon;
export const DotIcon = CheckIcon;
