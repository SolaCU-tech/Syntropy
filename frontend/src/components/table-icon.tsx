import {
  Banknote,
  Box,
  Package,
  Receipt,
  ShoppingCart,
  Table2,
  Truck,
  Users,
  Wallet,
  type LucideIcon,
} from 'lucide-react'

// The SSD names a Lucide icon per table. Importing all of Lucide would bloat the bundle, so
// common ones are mapped here and anything else falls back to a table icon.
const icons: Record<string, LucideIcon> = {
  users: Users,
  user: Users,
  package: Package,
  box: Box,
  'shopping-cart': ShoppingCart,
  receipt: Receipt,
  banknote: Banknote,
  wallet: Wallet,
  truck: Truck,
}

export function TableIcon({ name, className }: { name?: string | null; className?: string }) {
  const Icon = (name && icons[name]) || Table2
  return <Icon className={className} aria-hidden="true" />
}
