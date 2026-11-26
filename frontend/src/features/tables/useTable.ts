import { useParams } from 'react-router'

import { tableByKey, type Table } from '@/lib/ssd'
import { useSSD } from '@/features/workspace/context'

/** The table named by the :tableKey route parameter (URLs use the table key, spec section 15). */
export function useRouteTable(): Table | undefined {
  const { tableKey } = useParams()
  return tableByKey(useSSD(), tableKey ?? '')
}
