import { resources } from '../../configs';
import { ResourcePage } from '../../components/resource';
import { StocktakeCountAction } from '../../actions/StocktakeCountAction';

export function StocktakesPage() {
  return <ResourcePage config={{ ...resources['inventory.stocktakes'],
    customAction: (row, refresh, can) => <StocktakeCountAction row={row} refresh={refresh} canUpdate={can('update')} />,
  }} />;
}

