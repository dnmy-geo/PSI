import { resources } from '../../configs';
import { ResourcePage } from '../../components/resource';

export function ItemsPage() {
  return <ResourcePage config={resources['masterdata.items']} />;
}

