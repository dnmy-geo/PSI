import { resources } from '../../configs';
import { ResourcePage } from '../../components/resource';
import { PlanActions } from '../../actions/PlanActions';

export function ProductionPlansPage() {
  return <ResourcePage config={{ ...resources['production.plans'],
    customAction: (row, refresh, can) => <PlanActions row={row} refresh={refresh} canPost={can('post')} />,
  }} />;
}

